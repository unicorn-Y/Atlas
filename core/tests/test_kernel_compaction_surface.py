import pytest

from atlas.engine.kernel.context import compaction_surface


@pytest.mark.unit
def test_compaction_surface_changes_only_when_provider_history_changes():
    before = [{"role": "user", "content": "old history"}]
    same = [{"role": "user", "content": "old history"}]
    compacted = [{"role": "system", "content": "summary"}]

    assert compaction_surface(before) == compaction_surface(same)
    assert compaction_surface(before) != compaction_surface(compacted)
