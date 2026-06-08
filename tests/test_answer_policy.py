from pathlib import Path

import pytest

from docagent.models.base import HeuristicAnswerPolicy, ModelLoadError
from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig
from docagent.schemas import EvidenceBlock, EvidenceLocation


def _block() -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc1",
        page_id=1,
        block_id="b1",
        block_type="text",
        text="Date: March 12, 2020",
        location=EvidenceLocation(page=1, block_id="b1"),
    )


def test_heuristic_answer_policy_returns_generation_result() -> None:
    policy = HeuristicAnswerPolicy()

    result = policy.generate(question="What is the date?", evidence_blocks=[_block()], answer_type="extractive", qid="q1")

    assert result.parsed["evidence_location"]["block_id"] == "b1"
    assert result.raw_text.startswith("{")
    assert result.metadata["policy_mode"] == "heuristic"


def test_qwen_policy_rejects_missing_base_model_before_importing_runtime(tmp_path: Path) -> None:
    policy = QwenAnswerPolicy(
        QwenAnswerPolicyConfig(
            mode="base",
            base_model_path=str(tmp_path / "missing"),
            device="cpu",
        )
    )

    with pytest.raises(ModelLoadError, match="config.json"):
        policy.generate(question="What is the date?", evidence_blocks=[_block()])
