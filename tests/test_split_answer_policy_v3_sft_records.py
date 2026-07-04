from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.split_answer_policy_v3_sft_records import run_split


def _record(record_id: str, *, source: str = "tatqa", answer: str | None = None) -> dict:
    value = answer or f"answer {record_id}"
    target = {
        "answer": value,
        "supporting_refs": ["E1"],
        "support_status": "supported",
        "reasoning_summary": "The selected evidence contains the answer.",
    }
    return {
        "id": record_id,
        "source": source,
        "bucket": "evidence_extractive_supported",
        "messages": [
            {"role": "system", "content": "Return v3 JSON."},
            {"role": "user", "content": f"## Evidence Candidates\n[E1] Evidence says {value}."},
            {"role": "assistant", "content": json.dumps(target)},
        ],
    }


def test_split_answer_policy_v3_sft_records_writes_disjoint_train_and_heldout(tmp_path: Path) -> None:
    source_path = tmp_path / "train" / "sft_train.jsonl"
    write_jsonl(source_path, [_record(f"r{i}", source="mp_docvqa" if i % 2 else "tatqa") for i in range(10)])

    result = run_split(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="split",
        train_count=6,
        heldout_count=3,
        seed=7,
    )

    artifact_dir = tmp_path / "out" / "split"
    train = read_jsonl(artifact_dir / "train_sft.jsonl")
    heldout = read_jsonl(artifact_dir / "heldout_eval.jsonl")
    excluded = read_jsonl(artifact_dir / "excluded.jsonl")
    train_ids = {record["id"] for record in train}
    heldout_ids = {record["id"] for record in heldout}
    assert result["status"] == "success"
    assert result["valid_record_count"] == 10
    assert result["train_record_count"] == 6
    assert result["heldout_record_count"] == 3
    assert result["excluded_record_count"] == 1
    assert result["overlap_count"] == 0
    assert train_ids.isdisjoint(heldout_ids)
    assert len(excluded) == 1
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "manifest.json").is_file()


def test_split_answer_policy_v3_sft_records_blocks_validation_like_input(tmp_path: Path) -> None:
    source_path = tmp_path / "final_eval" / "sft_train.jsonl"
    write_jsonl(source_path, [_record("bad") for _ in range(3)])

    result = run_split(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="blocked",
        heldout_count=1,
    )

    assert result["status"] == "blocked"
    assert result["train_record_count"] == 0
    assert result["heldout_record_count"] == 0
    assert result["block_reasons"] == [f"validation_like_input_path:{source_path.as_posix()}:final_eval"]
    assert read_jsonl(tmp_path / "out" / "blocked" / "train_sft.jsonl") == []
    assert read_jsonl(tmp_path / "out" / "blocked" / "heldout_eval.jsonl") == []


def test_split_answer_policy_v3_sft_records_blocks_when_heldout_consumes_all_records(tmp_path: Path) -> None:
    source_path = tmp_path / "train" / "sft_train.jsonl"
    write_jsonl(source_path, [_record("r1"), _record("r2")])

    result = run_split(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="small",
        heldout_count=2,
    )

    assert result["status"] == "blocked"
    assert result["valid_record_count"] == 2
    assert result["block_reasons"] == ["not_enough_records_for_heldout"]
