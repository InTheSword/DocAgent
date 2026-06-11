from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path

from docagent.ingestion.hashing import doc_id_from_sha256, sha256_file


SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


@dataclass
class DocumentRecord:
    doc_id: str
    sha256: str
    original_name: str
    mime_type: str | None
    file_size: int
    file_path: str
    document_dir: str
    page_count: int | None = None
    parser_backend: str | None = None
    parse_status: str = "registered"
    index_status: str = "not_started"

    def to_dict(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "sha256": self.sha256,
            "original_name": self.original_name,
            "mime_type": self.mime_type,
            "file_size": self.file_size,
            "file_path": self.file_path,
            "document_dir": self.document_dir,
            "page_count": self.page_count,
            "parser_backend": self.parser_backend,
            "parse_status": self.parse_status,
            "index_status": self.index_status,
        }


class DocumentRegistry:
    def __init__(self, document_root: str | Path = "data/documents") -> None:
        self.document_root = Path(document_root)

    def register(self, file_path: str | Path) -> DocumentRecord:
        source = Path(file_path)
        if not source.exists():
            raise FileNotFoundError(source)
        extension = source.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"unsupported document type: {extension}")

        sha256 = sha256_file(source)
        doc_id = doc_id_from_sha256(sha256)
        document_dir = self.document_root / doc_id
        source_dir = document_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        target = source_dir / f"original{extension}"
        if not target.exists() or sha256_file(target) != sha256:
            shutil.copy2(source, target)

        mime_type = mimetypes.guess_type(source.name)[0]
        return DocumentRecord(
            doc_id=doc_id,
            sha256=sha256,
            original_name=source.name,
            mime_type=mime_type,
            file_size=source.stat().st_size,
            file_path=str(target),
            document_dir=str(document_dir),
        )

