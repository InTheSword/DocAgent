from __future__ import annotations

import json
from pathlib import Path

from docagent.rewards.combined import docqa_v3_reward, docqa_v3_reward_breakdown
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.calibrate_answer_policy_v3_rewards import run_calibration


def _record(record_id: str, *, status: str = "supported") -> dict:
    if status == "supported":
        target = {
            "answer": "March 12, 2020",
            "supporting_refs": ["E1"],
            "support_status": "supported",
            "reasoning_summary": "The selected evidence contains the answer.",
        }
        evidence = "[E1] Invoice date: March 12, 2020\n[E2] Vendor name: Acme"
    else:
        target = {
            "answer": "Insufficient evidence.",
            "supporting_refs": [],
            "support_status": "insufficient",
            "reasoning_summary": "No candidate contains the requested answer.",
        }
        evidence = "[E1] Vendor name: Acme\n[E2] Total due: $50"
    return {
        "id": record_id,
        "source": "tatqa",
        "messages": [
            {"role": "system", "content": "Return v3 JSON."},
            {"role": "user", "content": f"## Evidence Candidates\n{evidence}"},
            {"role": "assistant", "content": json.dumps(target)},
        ],
    }


def test_v3_reward_breakdown_penalizes_fabricated_insufficient_answer() -> None:
    good = {
        "answer": "Insufficient evidence.",
        "supporting_refs": [],
        "support_status": "insufficient",
        "reasoning_summary": "No candidate contains the answer.",
    }
    fabricated = {**good, "answer": "March 12, 2020"}

    good_breakdown = docqa_v3_reward_breakdown(good, "", positive_refs=[], insufficient_expected=True)
    fabricated_breakdown = docqa_v3_reward_breakdown(fabricated, "", positive_refs=[], insufficient_expected=True)

    assert good_breakdown["reward"] == 1.0
    assert fabricated_breakdown["reward"] < good_breakdown["reward"]
    assert docqa_v3_reward(good, "", positive_refs=[], insufficient_expected=True) == 1.0


def test_calibrate_answer_policy_v3_rewards_writes_report(tmp_path: Path) -> None:
    sft_path = tmp_path / "train" / "sft_train.jsonl"
    write_jsonl(sft_path, [_record("supported"), _record("insufficient", status="insufficient")])

    result = run_calibration(
        sft_inputs=[sft_path],
        output_root=tmp_path / "out",
        run_id="calibration",
    )

    artifact_dir = tmp_path / "out" / "calibration"
    rows = read_jsonl(artifact_dir / "rows.jsonl")
    metrics = result["metrics"]

    assert result["status"] == "success"
    assert result["used_training"] is False
    assert result["used_qwen"] is False
    assert result["validation_subset_used_for_training"] is False
    assert metrics["calibrated_record_count"] == 2
    assert metrics["reward_calibration_status"] == "passed"
    assert metrics["variant_summary"]["gold_target"]["min"] == 1.0
    assert metrics["variant_summary"]["fabricated_answer_with_insufficient_status"]["max"] < 0.85
    assert (artifact_dir / "summary.md").is_file()
    assert rows[0]["variants"][0]["variant"] == "gold_target"


def test_calibrate_answer_policy_v3_rewards_blocks_validation_like_input(tmp_path: Path) -> None:
    sft_path = tmp_path / "final_eval" / "sft_train.jsonl"
    write_jsonl(sft_path, [_record("blocked")])

    result = run_calibration(
        sft_inputs=[sft_path],
        output_root=tmp_path / "out",
        run_id="blocked",
    )

    assert result["status"] == "blocked"
    assert result["block_reasons"] == ["validation_like_input_path:" + sft_path.as_posix() + ":final_eval"]
