import json
from pathlib import Path

from atlas.memory.locomo_eval import run_locomo


def _dataset(path: Path) -> Path:
    rows = [{
        "sample_id": "synthetic-1",
        "qa": [
            {"question": "What pet does Maya have?", "answer": ["a parrot"], "category": 1,
             "is_multi_modality": False},
            {"question": "When did they meet?", "answer": ["June 3"], "category": 2,
             "is_multi_modality": True},
            {"question": "What color was the parrot?", "answer": ["green"], "category": 3,
             "is_multi_modality": False},
        ],
        "conversation": {
            "speaker_a": "Maya", "speaker_b": "Leo",
            "session_1_date_time": "1 June 2023",
            "session_1": [
                {"speaker": "Maya", "dia_id": "D1:2", "text": "My parrot is green."},
                {"speaker": "Leo", "dia_id": "D1:1", "text": "I met you on June 3."},
            ],
            "session_2_date_time": "4 June 2023",
            "session_2": [
                {"speaker": "Maya", "dia_id": "D2:2", "text": "I have a parrot named Kiwi."},
                {"speaker": "Leo", "dia_id": "D2:1", "text": "That parrot sounds lovely."},
            ],
        },
    }]
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_locomo_ingests_retrieves_judges_and_skips_multimodal(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "synthetic.json")
    memory_dir = tmp_path / "isolated-memory"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("untouched", encoding="utf-8")
    observed = []

    def judge(question, gold, evidence):
        observed.append((question, gold, evidence))
        if question == "What color was the parrot?":
            return "not JSON"
        return {"correct": "Kiwi" in evidence, "reason": "found in retrieved evidence"}

    result = run_locomo(dataset, data_dir=memory_dir, judge=judge, k=10)

    assert result["per_conversation"][0]["ingest_count"] == 4
    assert result["questions_skipped_multimodal"] == 1
    assert result["questions_evaluated"] == 2
    assert result["judge_errors"] == 1
    # 判分失败会重试 3 次（基础设施抖动不该污染分数），所以失败题贡献 3 次调用：
    # 1 次成功 + 1 题 x 3 次重试 = 4。
    assert len(observed) == 4
    assert any("parrot" in evidence.casefold() for _, _, evidence in observed)
    assert {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()} == {
        Path("synthetic.json"), Path("outside/keep.txt"),
        *{p.relative_to(tmp_path) for p in memory_dir.rglob("*") if p.is_file()},
    }
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "untouched"


def test_judge_non_json_counts_as_error_not_correct(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "synthetic.json")
    result = run_locomo(
        dataset, data_dir=tmp_path / "memory", judge=lambda *_args: "definitely not JSON",
        limit_questions=1,
    )
    assert result["judge_errors"] == 1
    assert result["accuracy_overall"] == 0.0
    assert not (tmp_path / "memory" / ".git").exists()
