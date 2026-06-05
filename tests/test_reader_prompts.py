from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from scripts.build_sft_dataset import EXTRACTION_RULES_TEXT, build_sft_record
from scripts.eval_sft_checkpoint import build_inference_messages


def _sample() -> DocAgentSample:
    return DocAgentSample(
        qid="q1",
        source="mp_docvqa",
        doc_id="doc1",
        question="Who is Longmont National Bank's president?",
        answer="john meyer",
        answer_type="extractive",
        evidence=[
            EvidenceBlock(
                doc_id="doc1",
                page_id=1,
                block_id="doc1_p1",
                block_type="text",
                text="john meyer president to Longmont National Bank. robert whyte president.",
                location=EvidenceLocation(page=1, block_id="doc1_p1"),
            )
        ],
        metadata={"gold_block_ids": ["doc1_p1"]},
    )


def test_sft_record_includes_strict_extraction_rules() -> None:
    record = build_sft_record(_sample(), max_evidence_blocks=1, max_block_chars=300, gold_first=True)
    user_content = record["messages"][1]["content"]

    assert EXTRACTION_RULES_TEXT in user_content
    assert "do not use outside knowledge" in user_content
    assert "neighboring entity" in user_content


def test_strict_extraction_is_opt_in_for_eval_prompts() -> None:
    record = build_sft_record(_sample(), max_evidence_blocks=1, max_block_chars=300, gold_first=True)

    default_messages = build_inference_messages(record, disable_thinking=True)
    strict_messages = build_inference_messages(record, disable_thinking=True, strict_extraction=True)

    assert "Additional extraction rules" not in default_messages[1]["content"]
    assert "Additional extraction rules" not in strict_messages[1]["content"]
    assert strict_messages[1]["content"].count(EXTRACTION_RULES_TEXT) == 1


def test_strict_extraction_adds_rules_to_legacy_eval_prompts() -> None:
    record = {
        "messages": [
            {"role": "system", "content": "Use only the provided evidence candidates."},
            {"role": "user", "content": "## Task\nAnswer from evidence."},
            {"role": "assistant", "content": "{}"},
        ]
    }

    strict_messages = build_inference_messages(record, disable_thinking=True, strict_extraction=True)

    assert "Additional extraction rules" in strict_messages[1]["content"]
    assert EXTRACTION_RULES_TEXT in strict_messages[1]["content"]
