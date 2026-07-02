from __future__ import annotations

import json
import hashlib
from pathlib import Path

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.build_answer_policy_training_pack import build_answer_policy_training_pack


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _sample(*, qid: str = "q1", split: str = "train", answer_type: str = "extractive") -> DocAgentSample:
    block = EvidenceBlock(
        doc_id="doc1",
        block_id=f"{qid}_b1",
        block_type="text",
        text="The invoice date is March 12, 2020.",
        page_id=1,
        location=EvidenceLocation(page=1, block_id=f"{qid}_b1"),
    )
    return DocAgentSample(
        qid=qid,
        source="training_fixture",
        doc_id="doc1",
        question="What is the invoice date?",
        answer="March 12, 2020",
        answer_type=answer_type,
        evidence=[block],
        split=split,
        metadata={"gold_block_ids": [block.block_id]},
    )


def test_build_training_pack_writes_sft_grpo_audit_and_manifest(tmp_path: Path) -> None:
    input_path = tmp_path / "train" / "samples.jsonl"
    write_jsonl(input_path, [_sample().to_dict()])

    result = build_answer_policy_training_pack(
        input_path=input_path,
        output_root=tmp_path / "packs",
        run_id="pack",
        max_evidence_blocks=3,
        max_block_chars=300,
    )

    assert result["status"] == "success"
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert result["sft_record_count"] == 1
    assert result["grpo_record_count"] == 1
    assert result["split_counts"] == {"train": 1}

    artifact_dir = tmp_path / "packs" / "pack"
    sft_records = read_jsonl(artifact_dir / "sft_train.jsonl")
    grpo_records = read_jsonl(artifact_dir / "grpo_train.jsonl")
    assert len(sft_records) == 1
    assert len(grpo_records) == 1
    assert [message["role"] for message in sft_records[0]["messages"]] == ["system", "user", "assistant"]
    assert [message["role"] for message in grpo_records[0]["messages"]] == ["system", "user"]
    assert "gold_answer" not in grpo_records[0]["messages"][-1]["content"]
    assert "assistant" not in {message["role"] for message in grpo_records[0]["messages"]}

    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["artifact_count"] == 7
    assert all(item["sha256"] for item in manifest["artifacts"])
    for item in manifest["artifacts"]:
        path = Path(item["path"])
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            path = artifact_dir / Path(item["path"]).name
        assert item["sha256"] == _sha256(path)
    assert (artifact_dir / "summary.md").is_file()


def test_training_pack_blocks_validation_like_splits_by_default(tmp_path: Path) -> None:
    input_path = tmp_path / "train" / "samples.jsonl"
    write_jsonl(input_path, [_sample(split="dev").to_dict()])

    result = build_answer_policy_training_pack(
        input_path=input_path,
        output_root=tmp_path / "packs",
        run_id="blocked",
    )

    assert result["status"] == "blocked"
    assert result["sft_record_count"] == 0
    assert result["grpo_record_count"] == 0
    assert result["block_reasons"] == ["non_train_sample_splits:dev"]
    assert read_jsonl(tmp_path / "packs" / "blocked" / "sft_train.jsonl") == []


def test_training_pack_blocks_validation_like_paths_by_default(tmp_path: Path) -> None:
    input_path = tmp_path / "final_eval" / "samples.jsonl"
    write_jsonl(input_path, [_sample().to_dict()])

    result = build_answer_policy_training_pack(
        input_path=input_path,
        output_root=tmp_path / "packs",
        run_id="blocked_path",
    )

    assert result["status"] == "blocked"
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]


def test_training_pack_allow_non_train_source_is_explicit(tmp_path: Path) -> None:
    input_path = tmp_path / "final_eval" / "samples.jsonl"
    write_jsonl(input_path, [_sample(split="dev").to_dict()])

    result = build_answer_policy_training_pack(
        input_path=input_path,
        output_root=tmp_path / "packs",
        run_id="allowed_fixture",
        allow_non_train_source=True,
    )

    assert result["status"] == "success"
    assert result["allow_non_train_source"] is True
    assert result["sft_record_count"] == 1
