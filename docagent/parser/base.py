from __future__ import annotations

from pathlib import Path
from typing import Protocol

from docagent.schemas import EvidenceBlock


class ParserBackend(Protocol):
    backend_name: str

    def parse(self, *, file_path: Path, doc_id: str, output_dir: Path) -> list[EvidenceBlock]:
        ...

