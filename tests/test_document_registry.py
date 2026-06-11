from __future__ import annotations

from pathlib import Path

from docagent.ingestion.document_registry import DocumentRegistry
from docagent.ingestion.hashing import sha256_file


def test_document_registry_uses_sha256_doc_id_and_reuses_source(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")
    registry = DocumentRegistry(tmp_path / "documents")

    first = registry.register(source)
    second = registry.register(source)

    assert first.doc_id == sha256_file(source)[:16]
    assert first.doc_id == second.doc_id
    assert Path(first.file_path).exists()
    assert first.file_path.endswith("original.pdf")

