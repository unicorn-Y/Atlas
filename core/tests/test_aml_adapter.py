from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import pytest

from atlas.memory.aml_adapter import MemoryAMLAdapter, run_locomo


class FakeLibrary:
    def __init__(self) -> None:
        self.page = SimpleNamespace(current=[])
        self.writes = []
        self.synced = False
        self.store = SimpleNamespace(
            lock=RLock(), read=lambda _rel: self.page,
            write=lambda page: self.writes.append(page),
            commit=lambda *_args, **_kwargs: pytest.fail("must not commit"),
        )
        self.index = SimpleNamespace(sync=self._sync)

    def _sync(self) -> None:
        self.synced = True

    def ready(self) -> None:
        pass

    def _safe_rel(self, rel: str) -> str:
        return rel

    def search(self, *_args, **_kwargs):
        return [{"text": "Alicia enjoys night trains", "score": 0.75}]


def test_add_and_search_contract_without_git_commit() -> None:
    library = FakeLibrary()
    adapter = MemoryAMLAdapter(library)

    entry_id = adapter.add(
        "  Alicia   enjoys night trains ",
        scope="project:alpha",
        meta={"ref": "locomo:q0001", "importance": 8},
    )
    hits = adapter.search("night trains", scope="project:alpha")

    assert entry_id
    assert library.page.current[0].id == entry_id
    assert library.page.current[0].text == "Alicia enjoys night trains"
    assert library.writes == [library.page]
    assert library.synced
    assert hits == [("Alicia enjoys night trains", 0.75)]


def test_run_locomo_reports_missing_dataset_with_source(tmp_path: Path) -> None:
    dataset = tmp_path / "locomo_refined.json"
    with pytest.raises(FileNotFoundError) as exc:
        run_locomo(dataset)

    assert str(dataset) in str(exc.value)
    assert "https://github.com/mem-eval-suite/LoCoMo_refined" in str(exc.value)


def test_run_locomo_forwards_existing_dataset(tmp_path: Path, monkeypatch) -> None:
    dataset = tmp_path / "locomo_refined.json"
    dataset.write_text("{}", encoding="utf-8")
    expected = {"accuracy_overall": 0.5}
    monkeypatch.setattr("atlas.memory.locomo_eval.run_locomo", lambda *args, **kwargs: expected)
    assert run_locomo(dataset, limit_conversations=1) == expected
