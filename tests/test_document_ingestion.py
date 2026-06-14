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
    assert stored_blocks[0].page_id == 1
    assert repository.get_document(doc_id)["parse_status"] == "parsed"
    assert (tmp_path / "documents" / doc_id / "structure_quality.json").is_file()


def test_document_ingestion_parse_existing_is_idempotent_and_writes_quality(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\n/Type /Page\nsample")
    doc_id = doc_id_from_sha256(sha256_file(source))
    mineru_dir = tmp_path / "documents" / doc_id / "mineru"
    mineru_dir.mkdir(parents=True)
    (mineru_dir / "sample_content_list.json").write_text(
        json.dumps(
            [
                {"type": "header", "page_idx": 0, "text": "Header", "bbox": [0, 0, 10, 10]},
                {"type": "text", "page_idx": 0, "text": "Body", "bbox": [0, 20, 10, 30]},
            ]
        ),
        encoding="utf-8",
    )
    conn = connect(tmp_path / "docagent.db")
    repository = DocumentRepository(conn)
    service = DocumentIngestionService(document_root=tmp_path / "documents", repository=repository)
    backend = MinerUParserBackend(mode="parse_existing", backend_name="mineru_existing")

    first = service.ingest(file_path=source, parser_backend=backend)
    second = service.ingest(file_path=source, parser_backend=backend)
    stored_blocks = repository.load_evidence_blocks(doc_id)
    quality = json.loads((tmp_path / "documents" / doc_id / "structure_quality.json").read_text(encoding="utf-8"))

    assert first.to_dict()["block_count"] == second.to_dict()["block_count"] == 2
    assert len(stored_blocks) == 2
    assert stored_blocks[0].metadata["is_boilerplate"] is True
    assert quality["boilerplate_count"] == 1
    assert quality["overall_status"] == "passed"
