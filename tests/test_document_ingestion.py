from __future__ import annotations

import json
from pathlib import Path

from docagent.ingestion.hashing import doc_id_from_sha256, sha256_file
from docagent.ingestion.service import DocumentIngestionService
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository


def test_document_ingestion_parse_existing_saves_document_and_blocks(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")
    doc_id = doc_id_from_sha256(sha256_file(source))
    mineru_dir = tmp_path / "documents" / doc_id / "mineru"
    mineru_dir.mkdir(parents=True)
    (mineru_dir / "sample_content_list.json").write_text(
        json.dumps([{"type": "text", "page_idx": 0, "text": "Invoice Date: March 12, 2020"}]),
        encoding="utf-8",
    )
    conn = connect(tmp_path / "docagent.db")
    repository = DocumentRepository(conn)
    service = DocumentIngestionService(document_root=tmp_path / "documents", repository=repository)

    result = service.ingest(file_path=source, parser_backend=MinerUParserBackend(mode="parse_existing"))
    stored_blocks = repository.load_evidence_blocks(doc_id)

    assert result.document.doc_id == doc_id
    assert result.to_dict()["block_count"] == 1
    assert stored_blocks[0].text == "Invoice Date: March 12, 2020"
    assert repository.get_document(doc_id)["parse_status"] == "parsed"

