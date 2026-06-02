from __future__ import annotations

from docagent.schemas import DocAgentSample, EvidenceBlock


def collect_evidence_blocks(samples: list[DocAgentSample]) -> list[EvidenceBlock]:
    blocks: dict[str, EvidenceBlock] = {}
    for sample in samples:
        for block in sample.evidence:
            blocks[block.block_id] = block
    return list(blocks.values())

