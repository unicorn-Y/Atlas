"""Read-only preparation audit; no production tests or network mutations."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RESEARCH = Path(__file__).resolve().parent
BASE = "9e6d6fde949a0f581ba7e0031004b1f6c4fdd2f4"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, encoding="utf-8"
    ).strip()


def main() -> None:
    errors: list[str] = []
    sources: list[dict] = []
    manifests = sorted(RESEARCH.glob("evidence-*.json"))
    if len(manifests) != 3:
        errors.append(f"expected three worker evidence manifests, found {len(manifests)}")
    for evidence in manifests:
        payload = json.loads(evidence.read_text(encoding="utf-8-sig"))
        for source in payload["sources"]:
            local = Path(source["local_root"])
            commit = source["commit"]
            if local.resolve() != ROOT.resolve() and git(local, "rev-parse", "HEAD") != commit:
                errors.append(f"commit mismatch: {source['repo']}")
            origin = git(local, "remote", "get-url", "origin")
            repo_id = source["repo"].removeprefix("https://github.com/").removesuffix(".git")
            if not origin.removesuffix(".git").endswith(repo_id):
                errors.append(f"origin mismatch: {source['repo']} -> {origin}")
            committed_at = git(local, "show", "-s", "--format=%cI", commit)
            if datetime.fromisoformat(committed_at).date() > date(2026, 10, 3):
                errors.append(f"post-cutoff source: {source['repo']} at {committed_at}")
            committed_files = set(git(local, "ls-tree", "-r", "--name-only", commit).splitlines())
            files = source["files"]
            if git(local, "diff", "--name-only", commit, "--", *files):
                errors.append(f"listed source differs from locked commit: {source['repo']}")
            for filename in files:
                if not (local / filename).is_file():
                    errors.append(f"source file missing: {source['repo']}:{filename}")
                if filename not in committed_files:
                    errors.append(f"file absent at locked commit: {source['repo']}:{filename}")
            sources.append({
                "repo": source["repo"], "commit": commit,
                "date": source["date"], "license": source["license"],
                "origin": origin, "committed_at": committed_at,
                "files_checked": len(files),
                "file_sha256": {
                    name: hashlib.sha256((local / name).read_bytes()).hexdigest()
                    for name in files if (local / name).is_file()
                },
            })
    books = sorted((ROOT / "tasks/taskbooks").glob("ATLAS-X[1-7]-*.md"))
    if len(books) != 7:
        errors.append(f"expected seven taskbooks, found {len(books)}")
    for index in range(1, 8):
        if len(list((ROOT / "tasks/taskbooks").glob(f"ATLAS-X{index}-*.md"))) != 1:
            errors.append(f"missing or duplicate X{index} taskbook")
    required = [
        "00-summary.md", "01-x1-sources.md", "02-x2-sources.md",
        "03-x3-sources.md", "04-x4-sources.md", "05-x5-sources.md",
        "06-x6-sources.md", "07-x7-products.md", "08-x7-architecture.md",
        "09-source-map.md",
    ]
    for filename in required:
        if not (RESEARCH / filename).is_file():
            errors.append(f"missing research: {filename}")
    changed = set(git(ROOT, "diff", "--name-only", BASE).splitlines())
    changed.update(git(ROOT, "ls-files", "--others", "--exclude-standard").splitlines())
    allowed = re.compile(
        r"^(docs/research/2026-10-03-x-prep/|tasks/taskbooks/ATLAS-X[1-7]-.*\.md$"
        r"|tasks/taskbooks/ATLAS-X-EXTERNAL-PHASE\.md$"
        r"|tasks/results/ATLAS-X-PREP\.result\.md$|tasks/SOL-CURRENT\.md$)"
    )
    for filename in sorted(changed):
        if filename and not allowed.match(filename):
            errors.append(f"out-of-scope change: {filename}")
    broken_links: list[str] = []
    for file in [*RESEARCH.glob("*.md"), *books]:
        text = file.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if re.match(r"^[a-zA-Z]+://", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if path and not (file.parent / path).exists():
                broken_links.append(f"{file.name}:{target}")
    errors.extend(f"broken local link: {link}" for link in broken_links)
    result = {
        "date": "2026-10-03", "atlas_base": BASE,
        "taskbooks": [str(p.relative_to(ROOT)).replace("\\", "/") for p in books],
        "sources": sources, "changed_files": sorted(changed), "errors": errors,
        "scope": "source commit/file existence/hash, artifact count, local links, allowlist",
        "not_verified": "product accounts, production implementation, real device behavior",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
