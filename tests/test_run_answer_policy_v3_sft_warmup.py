from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_answer_policy_v3_sft_warmup import run_warmup


def _record(record_id: str, *, source: str = "tatqa", answer: str = "March 12, 2020") -> dict:
    target = {
        "answer": answer,
        "supporting_refs": ["E1"],
        "support_status": "supported",
        "reasoning_summary": "The selected evidence contains the answer.",
    }
    return {
        "id": record_id,
        "source": source,
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


def test_answer_policy_v3_sft_warmup_dry_run_merges_records_and_writes_artifacts(tmp_path: Path) -> None:
    tatqa_path = tmp_path / "train" / "tatqa_sft.jsonl"
    mpdocvqa_path = tmp_path / "train" / "mpdocvqa_sft.jsonl"
    write_jsonl(tatqa_path, [_record("t1"), _record("t2")])
    write_jsonl(mpdocvqa_path, [_record("m1", source="mp_docvqa")])

    result = run_warmup(
        sft_inputs=[tatqa_path, mpdocvqa_path],
        output_root=tmp_path / "out",
        run_id="warmup",
        dry_run=True,
        max_records=3,
    )

    artifact_dir = tmp_path / "out" / "warmup"
    records = read_jsonl(artifact_dir / "warmup_train.jsonl")
    assert result["status"] == "success"
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert [record["id"] for record in records] == ["t1", "m1", "t2"]
    assert (artifact_dir / "result.json").is_file()
    assert (artifact_dir / "summary.json").is_file()
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "manifest.json").is_file()


def test_answer_policy_v3_sft_warmup_blocks_validation_like_inputs(tmp_path: Path) -> None:
    source_path = tmp_path / "final_eval" / "sft_train.jsonl"
    write_jsonl(source_path, [_record("bad")])

    result = run_warmup(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="blocked",
        dry_run=True,
    )

    assert result["status"] == "blocked"
    assert result["selected_record_count"] == 0
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]
    assert read_jsonl(tmp_path / "out" / "blocked" / "warmup_train.jsonl") == []
