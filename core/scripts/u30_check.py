"""Focused U30 regressions; uses local fixtures and never launches Electron."""

from __future__ import annotations

import asyncio
import runpy
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))


def require(path: str, *needles: str) -> None:
    content = (ROOT / path).read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in content]
    if missing:
        raise AssertionError(f"{path}: missing {missing}")


async def check_sites() -> None:
    from atlas.api import artifact_sites_router as sites
    from fastapi import HTTPException

    with tempfile.TemporaryDirectory(prefix="atlas-u30-") as temp:
        root = Path(temp)
        sites.DATA_ROOT = root / "data"
        workspace = root / "workspace"
        workspace.mkdir()
        source = workspace / "index.html"
        source.write_text("<!doctype html><h1>first version</h1>", encoding="utf-8")

        created = await sites.create_site({"workspace": str(workspace), "source_path": str(source), "title": "U30 fixture"})
        site = created["site"]
        site_id = site["id"]
        assert site["version"] == 1 and len(site_id) == 32
        stable_local = created["local_url"]
        assert "first version" in Path((await sites.open_site(site_id)).path).read_text(encoding="utf-8")

        page = await sites.add_site_page(site_id, {"slug": "overview", "title": "Overview", "content": "<script>text</script>"})
        assert page["local_url"].endswith("/overview/") and page["site"]["version"] == 2
        page_html = Path((await sites.open_site_asset(site_id, "overview/")).path).read_text(encoding="utf-8")
        assert "<h1>Overview</h1>" in page_html and "&lt;script&gt;" in page_html

        source.write_text("<!doctype html><h1>updated version</h1>", encoding="utf-8")
        updated = await sites.update_site_version(site_id, {"workspace": str(workspace), "source_path": str(source)})
        assert updated["site"]["id"] == site_id and updated["site"]["version"] == 3
        assert updated["local_url"] == stable_local
        assert "overview/" in Path((await sites.open_site(site_id)).path).read_text(encoding="utf-8")

        try:
            await sites.publish_site(site_id, {"confirmed": True, "terms_version": ""})
        except HTTPException as error:
            assert error.status_code == 409
        else:
            raise AssertionError("publishing without a configured destination was allowed")

        target = root / "hosting"
        settings = await sites.put_hosting_settings({
            "target_root": str(target), "public_base_url": "https://u30.invalid/sites",
            "terms_title": "U30 test terms", "terms_text": "Test deployment to a local fixture directory.",
            "terms_url": "https://u30.invalid/terms",
        })
        try:
            await sites.publish_site(site_id, {"confirmed": True, "terms_version": "stale"})
        except HTTPException as error:
            assert error.status_code == 428
        else:
            raise AssertionError("publishing with a stale terms version was allowed")
        published = await sites.publish_site(site_id, {"confirmed": True, "terms_version": settings["terms_version"]})
        assert published["share_url"] == f"https://u30.invalid/sites/{site_id}/"
        assert published["site"]["published_version"] == 3
        assert (target / site_id / "overview" / "index.html").is_file()
        assert "updated version" in (target / site_id / "index.html").read_text(encoding="utf-8")
        print("U30 item 3: local reopen, stable ID/version, child page and confirmed same-URL publish PASS")


async def main() -> None:
    # Reuse the previous wave's actual component protocol fixture for item 0.
    old_check = runpy.run_path(str(ROOT / "core/scripts/u29_check.py"))
    await old_check["check_structured_component_delivery"]()
    require("core/atlas/api/run_drive.py", 'event in {"component.push", "canvas.update"}', '"display_kind": "structured_component"')
    require("frontend/src/renderer/components/MessageThread.tsx", "structured_component", "component.push")
    print("U30 item 0: queued component protocol and persisted transcript reconstruction PASS")

    require("frontend/src/renderer/services/slashCommands.ts", "resolveSlashAvailability", "argumentHint", "frequency", "slashCommandUsage")
    require("frontend/src/renderer/App.tsx", "id: 'commands'", "id: 'redraw'", "whichKeyItems", "快捷键前缀提示")
    require("frontend/src/renderer/components/Composer.tsx", "atlas.slash-command-history", "disabledReason", "argumentHint")
    print("U30 item 1: command schema, availability, history and help wiring PASS")

    require("frontend/src/renderer/services/shortcuts.ts", "'tab1'", "'tab9'", "shortcutSignature")
    require("frontend/src/renderer/App.tsx", "const numberedTab = /^tab([1-9])$/", "const targetId = tabs[Number(numberedTab[1]) - 1]")
    print("U30 item 2: nine registered tab shortcuts and dispatch wiring PASS")

    require("frontend/src/renderer/shell/Inspector.tsx", "ArtifactSitesPanel")
    await check_sites()
    print("U30 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())
