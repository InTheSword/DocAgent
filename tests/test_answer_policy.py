from pathlib import Path

import pytest

from docagent.models.base import GenerationError, HeuristicAnswerPolicy, ModelLoadError
from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.workflow.prompts import compile_answer_prompt


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


class _CharTokenizer:
    def apply_chat_template(self, messages, **_kwargs):
        return "\n".join(f"{message['role']}:{message['content']}" for message in messages)

    def __call__(self, text, **_kwargs):
        return {"input_ids": list(range(len(text)))}


def test_qwen_prompt_budget_drops_evidence_before_question_or_instructions() -> None:
    tokenizer = _CharTokenizer()
    question = "KEEP_ORIGINAL_QUESTION"
    block = EvidenceBlock(
        doc_id="doc1",
        page_id=1,
        block_id="long",
        block_type="text",
        text="EVIDENCE " * 2000,
        location=EvidenceLocation(page=1, block_id="long"),
    )
    policy = QwenAnswerPolicy(
        QwenAnswerPolicyConfig(mode="base", max_prompt_tokens=2500),
        tokenizer=tokenizer,
        model=object(),
    )

    bundle, prompt, truncated = policy._compile_prompt_with_budget(
        tokenizer,
        compile_answer_prompt,
        {
            "question": question,
            "evidence_blocks": [block],
            "tool_results": None,
            "answer_type": "extractive",
            "append_no_think": False,
            "max_chars_per_block": 12000,
            "max_total_chars": None,
            "rank_aware_context": False,
        },
    )

    assert truncated is True
    assert question in prompt
    assert "You are DocAgent" in prompt
    assert len(tokenizer(prompt)["input_ids"]) <= 2500
    assert bundle.metadata["truncation_applied"] is True


def test_qwen_prompt_budget_rejects_limit_smaller_than_required_prompt() -> None:
    tokenizer = _CharTokenizer()
    policy = QwenAnswerPolicy(
        QwenAnswerPolicyConfig(mode="base", max_prompt_tokens=10),
        tokenizer=tokenizer,
        model=object(),
    )

    with pytest.raises(GenerationError, match="required instructions and question"):
        policy._compile_prompt_with_budget(
            tokenizer,
            compile_answer_prompt,
            {
                "question": "KEEP_ORIGINAL_QUESTION",
                "evidence_blocks": [_block()],
                "tool_results": None,
                "answer_type": "extractive",
                "append_no_think": False,
                "max_chars_per_block": 1200,
                "max_total_chars": None,
                "rank_aware_context": False,
            },
        )
