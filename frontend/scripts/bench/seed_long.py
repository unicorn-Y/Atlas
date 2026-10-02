# Bench seed: creates an isolated Atlas data dir with two 2000-message conversations.
# Run: core/.venv/Scripts/python.exe scripts/bench/seed_long.py <data-dir>   (ATLAS_DATA_DIR is set by the caller)
import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "core"))

from atlas.memory import MemoryStore  # noqa: E402  (import after ATLAS_DATA_DIR is set by caller)

MESSAGES_PER_CONVERSATION = 2000
LARGE_EVERY = 40


def large_markdown(index: int) -> str:
    parts = [f"# 第 {index} 号长输出\n\n下面是一段用来压测渲染的工程日志和代码。"]
    for block in range(8):
        parts.append(f"\n## 段落 {block}\n\n这一段解释了处理管线里第 {block} 步的细节，包含错误处理、重试策略和边界条件，方便测量 markdown + 高亮的解析开销。\n\n```python\n"
                     + "\n".join(f"def step_{block}_{line}(payload):  # 处理第 {line} 项\n    result = payload.transform({line}, verify=True)\n    return result if result.ok else None"
                                 for line in range(20)) + "\n```\n")
    return "\n".join(parts)


async def seed() -> None:
    db_path = DATA_DIR / "data" / "atlas.db"
    if db_path.exists():
        print(f"[seed] already seeded: {db_path}")
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    memory = MemoryStore()
    await memory.init()
    db = memory._db
    assert db is not None
    base = datetime(2026, 9, 1, 9, 0, 0)
    for conversation_index in (1, 2):
        conversation_id = str(uuid.uuid4())
        await db.execute("INSERT INTO conversations (id, title, updated_at) VALUES (?, ?, ?)",
                         (conversation_id, f"长会话 {chr(64 + conversation_index)}", base.isoformat()))
        rows = []
        moment = base
        for i in range(MESSAGES_PER_CONVERSATION):
            moment += timedelta(seconds=1)
            if i % 2 == 0:
                content = f"第 {i} 个问题：请帮我看看功能 {i} 的实现，需要注意哪些边界条件和错误处理？顺便给出一段示例代码。"
                role = "user"
            else:
                content = large_markdown(i) if i % (LARGE_EVERY * 2) == 1 else (
                    f"功能 {i} 的关键点有三处：入参校验、失败重试和结果缓存。"
                    "建议在入口处做一层防御式检查，错误路径上记录结构化日志，"
                    "重试采用指数退避，缓存按内容的哈希键存放。整体实现如下……" + "补充说明。" * 40
                )
                role = "assistant"
            rows.append((str(uuid.uuid4()), conversation_id, role, content, "{}", moment.isoformat()))
        await db.executemany(
            "INSERT INTO messages (id, conversation_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        print(f"[seed] conversation {conversation_index}: {len(rows)} messages")
    await db.commit()
    total = await (await db.execute("SELECT COUNT(*) FROM messages")).fetchone()
    print(f"[seed] total messages: {total[0]}, db: {db_path}")
    print(json.dumps({"data_dir": str(DATA_DIR), "db": str(db_path)}))
    await memory.close()


if __name__ == "__main__":
    asyncio.run(seed())
