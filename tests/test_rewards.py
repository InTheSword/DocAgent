from docagent.rewards.combined import docqa_reward


def _prediction(answer: str, block_id: str) -> dict:
    return {
        "answer": answer,
        "evidence_location": {"block_id": block_id},
        "evidence": "Acme Corporation",
        "reason": "The answer is supported by the cited OCR block.",
    }


def test_docqa_reward_counts_answer_only_when_location_matches() -> None:
    gold_location = {"block_id": "b1"}

    correct = docqa_reward(_prediction("Acme Corporation", "b1"), "Acme Corporation", gold_location, "extractive")
    wrong_location = docqa_reward(_prediction("Acme Corporation", "b2"), "Acme Corporation", gold_location, "extractive")
    wrong_answer = docqa_reward(_prediction("Globex", "b1"), "Acme Corporation", gold_location, "extractive")

    assert correct == 1.0
    assert wrong_location == 0.2
    assert wrong_answer == 0.4


def test_docqa_reward_without_gold_location_keeps_answer_credit() -> None:
    score = docqa_reward(_prediction("Acme Corporation", "b1"), "Acme Corporation", None, "extractive")

    assert score == 1.0
