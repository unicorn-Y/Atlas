"""Focused U29 integration checks that avoid launching Electron or a browser UI."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))


def check_source(path: str, needles: tuple[str, ...], label: str) -> None:
    content = (ROOT / path).read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in content]
    if missing:
        raise AssertionError(f"{label}: missing implementation markers: {missing}")


async def check_structured_component_delivery() -> None:
    from atlas.tools.structured_components import queue_component_event

    cases = [
        ("progress", {"steps": [{"label": "构建", "status": "active"}]}),
        ("table", {"columns": ["名称"], "rows": [["Atlas"]]}),
        ("metrics", {"metrics": [{"label": "完成率", "value": "80%"}]}),
        ("buttons", {"buttons": [{"label": "继续", "value": "continue"}]}),
    ]
    queue: asyncio.Queue[dict] = asyncio.Queue()
    for kind, data in cases:
        await queue_component_event({"title": kind, "kind": kind, "data": data}, "u29-run", queue)
    delivered = [await queue.get() for _ in cases]
    assert [item["type"] for item in delivered] == ["component.push"] * 4
    assert [item["data"]["kind"] for item in delivered] == [case[0] for case in cases]
    assert delivered[0]["data"]["component_id"] == "component-u29-run"
    try:
        await queue_component_event({"title": "bad", "kind": "buttons", "data": {"buttons": [{"label": "缺值"}]}}, "u29-run", queue)
    except ValueError:
        pass
    else:
        raise AssertionError("malformed interactive component was accepted")
    print("U29 component protocol: 4 valid kinds delivered; malformed button rejected")


async def main() -> None:
    await check_structured_component_delivery()
    check_source("frontend/src/renderer/App.tsx", ("label: '/powerup'", "message-timestamps", "atlas:chart-selection"), "command, timestamp and chart integration")
    check_source("frontend/src/renderer/components/FeatureLessons.tsx", ("LESSONS", "STORAGE_KEY", "SkipForward", "prefers-reduced-motion"), "interactive lessons")
    check_source("frontend/src/renderer/components/ConversationMessage.tsx", ("createdAt", "atlas.preference.message-timestamps", "<time dateTime={createdAt}"), "per-message timestamps")
    check_source("frontend/src/renderer/components/message-actions/CodeBlock.tsx", ("放大与批注", "selectedRows", "区域批注发送给 Atlas"), "table zoom and region feedback")
    check_source("frontend/src/renderer/shell/Inspector.tsx", ("在任务面板预览", "previewOnly"), "side-by-side artifact preview")
    check_source("frontend/src/renderer/components/ChaptersNav.tsx", ("自动目录", "matchAll(/^#{1,3}"), "automatic chapter index")
    check_source("frontend/src/renderer/components/MermaidBlock.tsx", ("选择图表节点", "回传给 Atlas"), "interactive diagram feedback")
    print("U29 lessons, timestamps, previews and chart interactions: wired")
    print("U29 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())
