from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from docagent.parser.mineru_converter import content_list_to_chunks
from docagent.schemas import Chunk


def run_mineru(input_path: str | Path, output_dir: str | Path, command: str = "mineru") -> Path:
    if shutil.which(command) is None:
        raise RuntimeError(f"{command} is not installed or not on PATH")
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([command, "-p", str(input_path), "-o", str(output_dir)], check=True)
    return output_dir


def content_list_to_blocks(doc_id: str, content_list_path: str | Path) -> list[Chunk]:
    """Compatibility entry point backed by the canonical MinerU-to-Chunk pipeline."""

    return content_list_to_chunks(
        doc_id=doc_id,
        content_list_path=content_list_path,
    )
