from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.select_answer_policy_v3_fixed_evidence_subset import build_fixed_evidence_subset


def _record(record_id: str, *, kind: str, source: str = "tatqa", status: str = "supported") -> dict:
    refs = ["E1"] if status == "supported" else []
    answer = "42" if status == "supported" else "Insufficient evidence."
    target = {
        "answer": answer,
        "supporting_refs": refs,
        "support_status": status,
        "reasoning_summary": "The selected evidence supports the answer."
        if status == "supported"
        else "The evidence candidates do not contain the answer.",
    }
    return {
        "id": record_id,
        "source": source,
        "messages": [
            {"role": "system", "content": "Return v3 JSON."},
            {
                "role": "user",
                "content": (
                    "## Question\nWhat is the value?\n\n"
                    "## Evidence Candidates\n"
                    f"[E1] kind={kind} page=1\n"
                    "Value: 42"
                ),
            },
            {"role": "assistant", "content": json.dumps(target)},
        ],
        "metadata": {
            "bucket": "insufficient_confirmed" if status == "insufficient" else "evidence_extractive_supported",
            "source": source,
        },
    }


def test_select_answer_policy_v3_fixed_evidence_subset_filters_table_and_calculation(tmp_path: Path) -> None:
    source_path = tmp_path / "train" / "sft_train.jsonl"
    write_jsonl(
        source_path,
        [
            _record("table", kind="table"),
            _record("calc", kind="calculation_result"),
            _record("text", kind="text"),
            _record("insufficient", kind="table", status="insufficient"),
        ],
    )

    result = build_fixed_evidence_subset(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="subset",
        include_kinds=["table", "calculation_result"],
        include_statuses=["supported"],
    )

    artifact_dir = tmp_path / "out" / "subset"
    selected = read_jsonl(artifact_dir / "eval_records.jsonl")
    rows = read_jsonl(artifact_dir / "rows.jsonl")
    assert result["status"] == "success"
    assert result["selected_record_count"] == 2
    assert {record["id"] for record in selected} == {"table", "calc"}
    assert result["category_counts"] == {"calculation_supported": 1, "table_value_supported": 1}
    assert result["target_kind_counts"] == {"calculation_result": 1, "table": 1}
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert len(rows) == 4
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "manifest.json").is_file()


def test_select_answer_policy_v3_fixed_evidence_subset_blocks_validation_like_input(tmp_path: Path) -> None:
    source_path = tmp_path / "final_eval" / "sft_train.jsonl"
    write_jsonl(source_path, [_record("bad", kind="table")])

    result = build_fixed_evidence_subset(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="blocked",
    )

    assert result["status"] == "blocked"
    assert result["selected_record_count"] == 0
    assert result["block_reasons"]
    assert result["block_reasons"][0].startswith("validation_like_input_path:")
    assert read_jsonl(tmp_path / "out" / "blocked" / "eval_records.jsonl") == []
