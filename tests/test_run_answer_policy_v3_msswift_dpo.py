from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_answer_policy_v3_msswift_dpo import run_msswift_dpo


def _prediction(answer: str) -> dict:
    return {
        "answer": answer,
        "supporting_refs": ["E1"],
        "support_status": "supported",
        "reasoning_summary": "The selected evidence contains the answer.",
    }


def _pair(record_id: str, *, ready: bool = True) -> dict:
    prompt_messages = [
        {"role": "system", "content": "Return v3 JSON."},
        {"role": "user", "content": "## Question\nWhat is the date?\n\n[E1] Date: March 12, 2020"},
    ]
    return {
        "id": record_id,
        "source": "tatqa",
        "prompt_messages": prompt_messages,
        "chosen": {"prediction": _prediction("March 12, 2020"), "reward": 1.0},
        "rejected": {"prediction": _prediction("April 1, 2020"), "reward": 0.6},
        "reward_margin": 0.4,
        "training_ready": ready,
        "not_training_ready_reasons": [] if ready else ["reward_margin_below_threshold"],
    }


def _adapter(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "adapter_config.json").write_text("{}", encoding="utf-8")
    return path


def test_answer_policy_v3_msswift_dpo_dry_run_writes_swift_artifacts(tmp_path: Path) -> None:
    pair_path = tmp_path / "train" / "preference_pairs.jsonl"
    adapter_path = _adapter(tmp_path / "adapter")
    write_jsonl(pair_path, [_pair("q1"), _pair("q2", ready=False)])

    result = run_msswift_dpo(
        preference_inputs=[pair_path],
        output_root=tmp_path / "out",
        run_id="dpo",
        adapter_path=adapter_path,
        max_records=8,
    )

    artifact_dir = tmp_path / "out" / "dpo"
    records = read_jsonl(artifact_dir / "swift_dpo_train.jsonl")
    command = json.loads((artifact_dir / "swift_command.json").read_text(encoding="utf-8"))["command"]

    assert result["status"] == "success"
    assert result["execute"] is False
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["selected_pair_count"] == 1
    assert result["validation_subset_used_for_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert records[0]["messages"][-1]["role"] == "assistant"
    assert "rejected_response" in records[0]
    assert "March 12, 2020" in records[0]["messages"][-1]["content"]
    assert "April 1, 2020" in records[0]["rejected_response"]
    assert "rlhf" in command
    assert "--rlhf_type" in command
    assert "dpo" in command
    assert "--adapters" in command
    assert "--ref_adapters" in command
    assert str(adapter_path) in command
    assert (artifact_dir / "result.json").is_file()
    assert (artifact_dir / "summary.json").is_file()
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "manifest.json").is_file()


def test_answer_policy_v3_msswift_dpo_blocks_validation_like_inputs(tmp_path: Path) -> None:
    pair_path = tmp_path / "final_eval" / "preference_pairs.jsonl"
    adapter_path = _adapter(tmp_path / "adapter")
    write_jsonl(pair_path, [_pair("q1")])

    result = run_msswift_dpo(
        preference_inputs=[pair_path],
        output_root=tmp_path / "out",
        run_id="blocked",
        adapter_path=adapter_path,
    )

    assert result["status"] == "blocked"
    assert result["selected_pair_count"] == 0
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]
    assert read_jsonl(tmp_path / "out" / "blocked" / "swift_dpo_train.jsonl") == []


def test_answer_policy_v3_msswift_dpo_blocks_missing_adapter(tmp_path: Path) -> None:
    pair_path = tmp_path / "train" / "preference_pairs.jsonl"
    write_jsonl(pair_path, [_pair("q1")])

    result = run_msswift_dpo(
        preference_inputs=[pair_path],
        output_root=tmp_path / "out",
        run_id="missing_adapter",
        adapter_path=tmp_path / "missing_adapter",
    )

    assert result["status"] == "blocked"
    assert result["selected_pair_count"] == 0
    assert result["block_reasons"] == [f"missing_adapter_path:{(tmp_path / 'missing_adapter').as_posix()}"]


def test_answer_policy_v3_msswift_dpo_execute_blocks_when_executable_missing(tmp_path: Path) -> None:
    pair_path = tmp_path / "train" / "preference_pairs.jsonl"
    adapter_path = _adapter(tmp_path / "adapter")
    missing_swift = tmp_path / "missing-swift"
    write_jsonl(pair_path, [_pair("q1")])

    result = run_msswift_dpo(
        preference_inputs=[pair_path],
        output_root=tmp_path / "out",
        run_id="missing",
        adapter_path=adapter_path,
        swift_executable=str(missing_swift),
        execute=True,
    )

    assert result["status"] == "blocked"
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["block_reasons"] == ["msswift_executable_not_found"]
