from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.generate_answer_policy_v3_candidates import generate_candidates


def _record(record_id: str = "q1") -> dict:
    target = {
        "answer": "March 12, 2020",
        "supporting_refs": ["E1"],
        "support_status": "supported",
        "reasoning_summary": "The selected evidence contains the answer.",
    }
    return {
        "id": record_id,
        "source": "tatqa",
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


def test_generate_answer_policy_v3_candidates_dry_run_writes_candidate_file(tmp_path: Path) -> None:
    sft_path = tmp_path / "train" / "sft_train.jsonl"
    write_jsonl(sft_path, [_record("q1"), _record("q2")])

    result = generate_candidates(
        sft_inputs=[sft_path],
        output_root=tmp_path / "out",
        run_id="candidates",
        limit=2,
        num_candidates=2,
        dry_run=True,
    )

    artifact_dir = tmp_path / "out" / "candidates"
    rows = read_jsonl(artifact_dir / "candidates.jsonl")

    assert result["status"] == "success"
    assert result["used_training"] is False
    assert result["used_qwen"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["metrics"]["record_count"] == 2
    assert result["metrics"]["candidate_count"] == 4
    assert result["metrics"]["candidate_source_counts"] == {"synthetic_dry_run": 4}
    assert rows[0]["candidates"][0]["candidate_source"] == "synthetic_dry_run"
    assert rows[0]["candidates"][0]["schema_ok"] is True
    assert (artifact_dir / "summary.md").is_file()


def test_generate_answer_policy_v3_candidates_blocks_validation_like_input(tmp_path: Path) -> None:
    sft_path = tmp_path / "final_eval" / "sft_train.jsonl"
    write_jsonl(sft_path, [_record("q1")])

    result = generate_candidates(
        sft_inputs=[sft_path],
        output_root=tmp_path / "out",
        run_id="blocked",
        dry_run=True,
    )

    assert result["status"] == "blocked"
    assert result["block_reasons"] == [f"validation_like_input_path:{sft_path.as_posix()}:final_eval"]
    assert read_jsonl(tmp_path / "out" / "blocked" / "candidates.jsonl") == []
