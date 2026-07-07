from __future__ import annotations

from pathlib import Path
from typing import Any

from docagent.schemas import EvidenceBlock
from docagent.tools.visual_summary import visual_observation_for_block


def visual_review(
    block: EvidenceBlock,
    question: str,
    *,
    mode: str = "off",
    document_dir: str | Path | None = None,
    env_file: Path | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    return visual_observation_for_block(
        block,
        question,
        mode=mode,
        document_dir=document_dir,
        env_file=env_file,
        client=client,
    )
