from __future__ import annotations

import re

from docagent.schemas import EvidenceBlock


def heuristic_answer(question: str, blocks: list[EvidenceBlock]) -> dict[str, object]:
    if not blocks:
        return {
            "answer": "I cannot answer from the provided evidence.",
            "evidence_location": {},
            "evidence": "",
            "reason": "No evidence was retrieved.",
        }
    block = blocks[0]
    evidence = block.retrieval_text
    lowered = question.lower()
    if "date" in lowered:
        pattern = r"(?:invoice\s+date|date)[:：]\s*([A-Za-z0-9$.,% -]+)"
    elif "invoice" in lowered and ("number" in lowered or "no" in lowered):
        pattern = r"(?:invoice\s+no|invoice\s+number)[:：]\s*([A-Za-z0-9$.,% -]+)"
    elif any(term in lowered for term in ["revenue", "total", "amount"]):
        pattern = r"(?:revenue|total|amount)[:：]\s*([A-Za-z0-9$.,% -]+)"
    else:
        pattern = r"(?:answer|date|revenue|invoice(?: no)?|total)[:：]\s*([A-Za-z0-9$.,% -]+)"
    match = re.search(pattern, evidence, flags=re.I)
    answer = match.group(1).strip() if match else evidence.splitlines()[0][:120]
    return {
        "answer": answer,
        "evidence_location": block.location.to_dict(),
        "evidence": evidence[:500],
        "reason": "The answer is generated from the top retrieved evidence block.",
    }
