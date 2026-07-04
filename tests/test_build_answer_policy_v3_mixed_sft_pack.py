from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.build_answer_policy_v3_mixed_sft_pack import build_mixed_pack


def _record(record_id: str, *, source: str = "tatqa", status: str = "supported") -> dict:
    target = {
        "answer": "March 12, 2020" if status == "supported" else "Insufficient evidence.",
        "supporting_refs": ["E1"] if status == "supported" else [],
        "support_status": status,
        "reasoning_summary": "The selected evidence contains the answer."
        if status == "supported"
        else "The provided evidence is insufficient.",
    }
    return {
        "id": record_id,
        "source": source,
        "bucket": "insufficient_confirmed" if status == "insufficient" else "evidence_extractive_supported",
        "messages": [
            {
                "role": "system",
                "content": "Return exactly one valid JSON object with answer, supporting_refs, support_status, and reasoning_summary.",
            },
            {
                "role": "user",
                "content": "## Question\nWhat is the invoice date?\n\n## Evidence Candidates\n[E1] Invoice Date: March 12, 2020",
            },
            {"role": "assistant", "content": json.dumps(target)},
        ],
    }


def test_answer_policy_v3_mixed_pack_applies_ratios_and_backfills_shortage(tmp_path: Path) -> None:
    tatqa_path = tmp_path / "train" / "tatqa_sft.jsonl"
    mpdocvqa_path = tmp_path / "train" / "mpdocvqa_sft.jsonl"
    insufficient_path = tmp_path / "train" / "insufficient_sft.jsonl"
    write_jsonl(tatqa_path, [_record(f"t{i}", source="tatqa") for i in range(5)])
    write_jsonl(mpdocvqa_path, [_record(f"m{i}", source="mp_docvqa") for i in range(3)])
    write_jsonl(insufficient_path, [_record(f"n{i}", source="tatqa", status="insufficient") for i in range(2)])

    result = build_mixed_pack(
        tatqa_sft=tatqa_path,
        mpdocvqa_sft=mpdocvqa_path,
        insufficient_sft=insufficient_path,
        output_root=tmp_path / "out",
        run_id="mixed",
        target_records=10,
        mpdocvqa_ratio=0.5,
        tatqa_ratio=0.4,
        insufficient_ratio=0.1,
    )

    artifact_dir = tmp_path / "out" / "mixed"
    records = read_jsonl(artifact_dir / "sft_train.jsonl")
    assert result["status"] == "success"
    assert result["selected_record_count"] == 10
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert result["selection_plan"]["initial_quotas"] == {"insufficient": 1, "mpdocvqa": 5, "tatqa": 4}
    assert result["selection_plan"]["shortage_counts"] == {"mpdocvqa": 2}
    assert result["selection_plan"]["selected_category_counts"] == {"insufficient": 2, "mpdocvqa": 3, "tatqa": 5}
    assert len(records) == 10
    assert (artifact_dir / "source_audit.json").is_file()
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "manifest.json").is_file()


def test_answer_policy_v3_mixed_pack_blocks_validation_like_input(tmp_path: Path) -> None:
    source_path = tmp_path / "final_eval" / "sft_train.jsonl"
    write_jsonl(source_path, [_record("bad")])

    result = build_mixed_pack(
        tatqa_sft=source_path,
        output_root=tmp_path / "out",
        run_id="blocked",
    )

    assert result["status"] == "blocked"
    assert result["selected_record_count"] == 0
    assert result["block_reasons"] == [f"validation_like_input_path:{source_path.as_posix()}:final_eval"]
    assert read_jsonl(tmp_path / "out" / "blocked" / "sft_train.jsonl") == []


def test_answer_policy_v3_mixed_pack_filters_invalid_records(tmp_path: Path) -> None:
    source_path = tmp_path / "train" / "tatqa_sft.jsonl"
    invalid = {"id": "bad", "messages": [{"role": "user", "content": "missing assistant"}]}
    write_jsonl(source_path, [_record("ok"), invalid])

    result = build_mixed_pack(
        tatqa_sft=source_path,
        output_root=tmp_path / "out",
        run_id="filtered",
        target_records=2,
        tatqa_ratio=1,
        mpdocvqa_ratio=0,
        insufficient_ratio=0,
    )

    source_audit = json.loads((tmp_path / "out" / "filtered" / "source_audit.json").read_text(encoding="utf-8"))
    assert result["status"] == "success"
    assert result["selected_record_count"] == 1
    assert source_audit["tatqa"]["input_record_count"] == 2
    assert source_audit["tatqa"]["valid_record_count"] == 1
    assert source_audit["tatqa"]["invalid_reason_counts"] == {"missing_messages": 1}
