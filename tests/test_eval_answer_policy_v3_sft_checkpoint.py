from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.eval_answer_policy_v3_sft_checkpoint import decode_first_json_object, run_eval, score_prediction


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
            {"role": "system", "content": "Return v3 JSON."},
            {"role": "user", "content": "## Evidence Candidates\n[E1] Invoice Date: March 12, 2020"},
            {"role": "assistant", "content": json.dumps(target)},
        ],
    }


def test_decode_first_json_object_recovers_embedded_v3_json() -> None:
    parsed = decode_first_json_object('prefix {"answer":"A","supporting_refs":["E1"],"support_status":"supported","reasoning_summary":"R"} tail')

    assert parsed == {
        "answer": "A",
        "supporting_refs": ["E1"],
        "support_status": "supported",
        "reasoning_summary": "R",
    }


def test_score_prediction_checks_v3_schema_refs_and_answer() -> None:
    record = _record()
    prediction = json.loads(record["messages"][-1]["content"])

    metrics = score_prediction(record, prediction, json.dumps(prediction))
    bad_ref = score_prediction(record, {**prediction, "supporting_refs": ["E9"]}, json.dumps(prediction))

    assert metrics["json_ok"] is True
    assert metrics["schema_ok"] is True
    assert metrics["answer_exact"] is True
    assert metrics["positive_ref_hit"] is True
    assert bad_ref["schema_ok"] is False
    assert bad_ref["positive_ref_hit"] is False


def test_eval_answer_policy_v3_checkpoint_dry_run_writes_artifacts(tmp_path: Path) -> None:
    sft_path = tmp_path / "train" / "sft_train.jsonl"
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    write_jsonl(sft_path, [_record()])

    result = run_eval(
        sft_input=sft_path,
        adapter_path=adapter_path,
        output_root=tmp_path / "out",
        run_id="eval",
        dry_run=True,
    )

    artifact_dir = tmp_path / "out" / "eval"
    assert result["status"] == "success"
    assert result["used_training"] is False
    assert result["used_qwen"] is False
    assert result["validation_subset_used_for_training"] is False
    assert (artifact_dir / "result.json").is_file()
    assert (artifact_dir / "summary.json").is_file()
    assert read_jsonl(artifact_dir / "rows.jsonl") == []


def test_eval_answer_policy_v3_checkpoint_dry_run_allows_base_only(tmp_path: Path) -> None:
    sft_path = tmp_path / "train" / "sft_train.jsonl"
    write_jsonl(sft_path, [_record()])

    result = run_eval(
        sft_input=sft_path,
        output_root=tmp_path / "out",
        run_id="base_only",
        dry_run=True,
    )

    assert result["status"] == "success"
    assert result["adapter_path"] == ""
    assert result["model_mode"] == "base_only"
    assert result["used_qwen"] is False


def test_eval_answer_policy_v3_checkpoint_blocks_validation_like_input(tmp_path: Path) -> None:
    sft_path = tmp_path / "final_eval" / "sft_train.jsonl"
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    write_jsonl(sft_path, [_record()])

    result = run_eval(
        sft_input=sft_path,
        adapter_path=adapter_path,
        output_root=tmp_path / "out",
        run_id="blocked",
        dry_run=True,
    )

    assert result["status"] == "blocked"
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]
