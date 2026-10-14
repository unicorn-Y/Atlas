from atlas.kernel.context import ContextManager


def _tool_call(
    call_id: str, content: str, *, name: str = "read_file", path: str = "src/example.py"
):
    return [
        {
            "role": "assistant",
            "tool_calls": [{"id": call_id, "name": name, "arguments": {"path": path}}],
        },
        {"role": "tool", "tool_call_id": call_id, "content": content},
    ]


def test_prune_keeps_recent_results_and_requires_minimum_savings(tmp_path):
    history = []
    history.extend(_tool_call("old-1", "a" * 100_000))
    history.extend(_tool_call("old-2", "b" * 100_000))
    history.extend(_tool_call("recent", "c" * 120_000))
    manager = ContextManager(output_dir=tmp_path)

    compacted, pruned, deduped, invalidated = manager._prune_and_dedupe(
        history,
        budget_tokens=200_000,
        context_tokens=150_000,
    )

    assert pruned == 2
    assert deduped == 0
    assert compacted[-1]["content"] == history[-1]["content"]
    assert "exit_code" not in compacted[1]["content"]
    assert all(call_id in invalidated for call_id in ("old-1", "old-2"))
    assert len(list(tmp_path.glob("*.txt"))) == 2


def test_prune_does_nothing_when_eligible_outputs_cannot_recover_minimum(tmp_path):
    history = []
    history.extend(_tool_call("old", "a" * 50_000))
    history.extend(_tool_call("recent", "b" * 100_000))
    manager = ContextManager(output_dir=tmp_path)

    compacted, pruned, deduped, invalidated = manager._prune_and_dedupe(
        history,
        budget_tokens=200_000,
        context_tokens=150_000,
    )

    assert compacted == history
    assert (pruned, deduped, invalidated) == (0, 0, [])


def test_prepare_summarizes_serialized_history_and_uses_primary_fallback():
    async def scenario():
        manager = ContextManager({"engine": {"keep_recent_tokens": 100}})
        history = [
            {"role": "user", "content": "Continue the task."},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "read-1", "name": "read_file", "arguments": {"path": "src/example.py"}}
                ],
            },
            {"role": "tool", "tool_call_id": "read-1", "content": "file contents"},
            {"role": "assistant", "content": "prior work " * 30_000},
            {"role": "user", "content": "Next step."},
            {"role": "assistant", "content": "ready"},
        ]
        attempts = []

        async def configured_summary(messages, prompt):
            attempts.append("configured")
            assert messages[0]["role"] == "user"
            assert "[Assistant]:" in messages[0]["content"]
            raise RuntimeError("summary route down")

        async def primary_summary(messages, prompt):
            attempts.append("primary")
            return (
                "Goal\nConstraints and preferences\nProgress\nKey decisions\nNext steps\n"
                "Key context\nUser's exact words\nprior work\n"
            )

        manager.set_summary_fallback(primary_summary)
        result = await manager.prepare(
            history, model_window=200_000, summarize=configured_summary, force=True
        )
        assert result.method == "summary"
        assert result.error is None
        assert attempts == ["configured", "configured", "primary", "primary"]
        assert "Continue the task." in result.messages[0]["content"]
        assert result.read_files == ["src/example.py"]

    import asyncio

    asyncio.run(scenario())
