#!/usr/bin/env python3
"""LongMemEval subset sampler for Atlas Memory-V1 (Package F / S8).

Samples 120 questions (20 per category across 6 categories) from LongMemEval_S
with a fixed random seed (20261007) and produces:
    D:/Atlas/docs/plan/MEMORY-V1/eval/longmemeval_subset.json

Upstream reference:
- Repository: https://github.com/xiaowu0162/LongMemEval (MIT License)
- Pinned commit: 9e0b455f4ef0e2ab8f2e582289761153549043fc
- HuggingFace dataset: xiaowu0162/longmemeval, file: longmemeval_s
- Dataset sha256: 08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

UPSTREAM_REPO = "https://github.com/xiaowu0162/LongMemEval"
UPSTREAM_COMMIT = "9e0b455f4ef0e2ab8f2e582289761153549043fc"
HF_DATASET_REPO = "xiaowu0162/longmemeval"
HF_REVISION = "2ec2a557f339b6c0369619b1ed5793734cc87533"
CANONICAL_FILENAME = "longmemeval_s"
CANONICAL_SHA256 = "08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894"

DEFAULT_SEED = 20261007
SAMPLES_PER_CATEGORY = 20

CANONICAL_CATEGORIES = [
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
]

DEFAULT_OUTPUT_PATH = Path(
    r"D:\Atlas\docs\plan\MEMORY-V1\eval\longmemeval_subset.json"
)

# Known local fallbacks on this machine if offline
KNOWN_LOCAL_CANDIDATES = [
    Path(r"C:\Users\25011\Documents\codex\2026-10-06\zhe\work\memory-research\Graphiti\tests\evals\data\longmemeval_data\longmemeval_oracle.json"),
    Path(r"D:\Atlas\data\longmemeval_s.json"),
]


def compute_sha256(path: Path) -> str:
    """Compute sha256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def download_dataset(target_path: Path) -> None:
    """Download longmemeval_s from Hugging Face."""
    url = f"https://huggingface.co/datasets/{HF_DATASET_REPO}/resolve/{HF_REVISION}/{CANONICAL_FILENAME}"
    print(f"Downloading LongMemEval_S from {url} to {target_path} ...")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Atlas-Eval/1.0"})
    with urllib.request.urlopen(req) as resp, open(target_path, "wb") as out:
        downloaded = 0
        while chunk := resp.read(1024 * 1024):
            out.write(chunk)
            downloaded += len(chunk)
            print(f"  Downloaded {downloaded / (1024 * 1024):.1f} MB...", end="\r")
    print(f"\nDownload completed. Computing SHA256...")
    sha = compute_sha256(target_path)
    print(f"File SHA256: {sha}")
    if sha != CANONICAL_SHA256:
        print(f"WARNING: SHA256 mismatch! Expected {CANONICAL_SHA256}, got {sha}")


def load_dataset(source_path: Path | None) -> tuple[list[dict[str, Any]], str | None, str]:
    """Load questions from an explicit path or known candidates."""
    target: Path | None = source_path
    if not target or not target.exists():
        for candidate in KNOWN_LOCAL_CANDIDATES:
            if candidate.exists():
                target = candidate
                break

    if not target or not target.exists():
        raise FileNotFoundError(
            "LongMemEval dataset not found locally. Pass --source <path> or use --download.\n"
            f"Official download URL: https://huggingface.co/datasets/{HF_DATASET_REPO}/resolve/{HF_REVISION}/{CANONICAL_FILENAME}\n"
            f"Expected SHA256: {CANONICAL_SHA256}"
        )

    print(f"Loading dataset from: {target}")
    file_sha256 = compute_sha256(target)
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array of question objects, got {type(data)}")

    return data, file_sha256, str(target)


def sample_subset(
    questions: list[dict[str, Any]],
    seed: int = DEFAULT_SEED,
    per_category: int = SAMPLES_PER_CATEGORY,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Perform stratified random sampling across 6 categories.
    
    To guarantee 100% deterministic results regardless of file format or ordering,
    the candidate questions in each category are sorted by question_id before sampling.
    """
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q in questions:
        q_type = q.get("question_type")
        if q_type in CANONICAL_CATEGORIES:
            by_category[q_type].append(q)

    # Check categories coverage
    for cat in CANONICAL_CATEGORIES:
        if len(by_category[cat]) < per_category:
            raise ValueError(
                f"Category '{cat}' only has {len(by_category[cat])} questions, "
                f"cannot sample {per_category}"
            )

    rng = random.Random(seed)
    sampled_ids_by_cat: dict[str, list[str]] = {}
    sampled_questions: list[dict[str, Any]] = []

    for cat in CANONICAL_CATEGORIES:
        # Deterministic pool ordering by question_id
        pool = sorted(by_category[cat], key=lambda x: str(x.get("question_id", "")))
        chosen = rng.sample(pool, per_category)
        
        # Sort chosen items by question_id for consistent presentation
        chosen.sort(key=lambda x: str(x.get("question_id", "")))
        
        sampled_ids_by_cat[cat] = [str(q["question_id"]) for q in chosen]
        for q in chosen:
            # Keep clean question representation (excluding giant haystack to keep subset JSON light)
            sampled_questions.append({
                "question_id": q.get("question_id"),
                "question_type": q.get("question_type"),
                "question": q.get("question"),
                "answer": q.get("answer"),
                "question_date": q.get("question_date"),
                "answer_session_ids": q.get("answer_session_ids", []),
                "haystack_session_count": len(q.get("haystack_session_ids", [])),
                "is_abstention": str(q.get("question_id", "")).endswith("_abs"),
            })

    return sampled_ids_by_cat, sampled_questions


def run_sampling(
    source_path: Path | None,
    output_path: Path,
    seed: int = DEFAULT_SEED,
    per_category: int = SAMPLES_PER_CATEGORY,
    do_download: bool = False,
    download_dir: Path | None = None,
) -> Path:
    """Execute sampling workflow and write longmemeval_subset.json."""
    if do_download:
        dl_dir = download_dir or Path(r"D:\Atlas\docs\plan\MEMORY-V1\eval\dataset")
        target_file = dl_dir / CANONICAL_FILENAME
        download_dataset(target_file)
        source_path = target_file

    data, file_sha, source_desc = load_dataset(source_path)
    print(f"Loaded {len(data)} total questions from {source_desc}.")

    sampled_ids_by_cat, sampled_questions = sample_subset(
        data, seed=seed, per_category=per_category
    )

    all_sampled_ids: list[str] = []
    for cat in CANONICAL_CATEGORIES:
        all_sampled_ids.extend(sampled_ids_by_cat[cat])

    output_doc: dict[str, Any] = {
        "metadata": {
            "title": "LongMemEval Stratified Evaluation Subset (120 questions)",
            "upstream_repo": UPSTREAM_REPO,
            "upstream_commit": UPSTREAM_COMMIT,
            "dataset_repo_id": HF_DATASET_REPO,
            "dataset_revision": HF_REVISION,
            "canonical_filename": CANONICAL_FILENAME,
            "canonical_sha256": CANONICAL_SHA256,
            "source_file_used": source_desc,
            "source_file_sha256": file_sha,
            "random_seed": seed,
            "samples_per_category": per_category,
            "total_sampled": len(all_sampled_ids),
        },
        "categories": CANONICAL_CATEGORIES,
        "sampled_question_ids_by_category": sampled_ids_by_cat,
        "all_sampled_question_ids": all_sampled_ids,
        "questions": sampled_questions,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Successfully saved {len(all_sampled_ids)} sampled questions to: {output_path}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Path to LongMemEval dataset JSON file (longmemeval_s or longmemeval_oracle.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to write longmemeval_subset.json",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for sampling (default: 20261007)",
    )
    parser.add_argument(
        "--per-category",
        type=int,
        default=SAMPLES_PER_CATEGORY,
        help="Number of questions per category (default: 20)",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the full canonical longmemeval_s from Hugging Face",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=None,
        help="Directory to store downloaded dataset file",
    )
    args = parser.parse_args()

    run_sampling(
        source_path=args.source,
        output_path=args.output,
        seed=args.seed,
        per_category=args.per_category,
        do_download=args.download,
        download_dir=args.download_dir,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
