from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRegistry
from docagent.ingestion.hashing import doc_id_from_sha256, sha256_file
from docagent.ingestion.service import DocumentIngestionService
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.schemas import EvidenceBlock
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl


def _json_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mineru_existing_artifacts_are_portable_after_document_dir_move(tmp_path: Path) -> None:
    old_root = tmp_path / "old_root"
    new_root = tmp_path / "new_root"
    source = old_root / "source.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-1.4\n/Type /Page\n/Type /Page\nsource")
    doc_id = doc_id_from_sha256(sha256_file(source))
    document_root = old_root / "documents"
    preview = DocumentRegistry(document_root).register(source)
    doc_dir = Path(preview.document_dir)
    shutil.copytree("tests/fixtures/mineru_real_schema", doc_dir / "mineru")
    conn = connect(old_root / "docagent.sqlite")
    service = DocumentIngestionService(document_root=document_root, repository=DocumentRepository(conn))

    service.ingest(
        file_path=source,
        parser_backend=MinerUParserBackend(mode="parse_existing", backend_name="mineru_existing"),
        force_parse=True,
    )
    conn.close()

    moved_doc_dir = new_root / "documents" / doc_id
    moved_doc_dir.parent.mkdir(parents=True)
    shutil.copytree(doc_dir, moved_doc_dir)
    moved_sqlite = new_root / "docagent.sqlite"
    shutil.copy2(old_root / "docagent.sqlite", moved_sqlite)
    old_root_text = str(old_root)
    shutil.rmtree(old_root)

    blocks = [EvidenceBlock.from_dict(record) for record in read_jsonl(moved_doc_dir / "evidence_blocks.jsonl")]
    pages = [EvidenceBlock.from_dict(record) for record in read_jsonl(moved_doc_dir / "page_documents.jsonl")]
    image_blocks = [block for block in blocks if block.image_path]

    assert blocks
    assert pages
    assert all(not Path(block.image_path).is_absolute() for block in image_blocks)
    assert all((moved_doc_dir / block.image_path).is_file() for block in image_blocks)
    for block in blocks:
        provenance = block.metadata.get("mineru_provenance") or {}
        if "content_list_file" in provenance:
            assert (moved_doc_dir / provenance["content_list_file"]).is_file()
        if "layout_path" in provenance:
            assert (moved_doc_dir / provenance["layout_path"]).is_file()
        assert "normalized_resource_path" not in block.metadata
        assert "source_content_list" not in block.metadata
    assert any(block.metadata.get("is_boilerplate") for block in blocks)
    for index, block in enumerate(blocks):
        if index > 0:
            assert block.metadata["previous_block_id"] == blocks[index - 1].block_id
        if index + 1 < len(blocks):
            assert block.metadata["next_block_id"] == blocks[index + 1].block_id

    persisted_text = "\n".join(
        [
            _json_text(moved_doc_dir / "evidence_blocks.jsonl"),
            _json_text(moved_doc_dir / "page_documents.jsonl"),
            _json_text(moved_doc_dir / "ingestion_report.json"),
            _json_text(moved_doc_dir / "structure_quality.json"),
        ]
    )
    assert old_root_text not in persisted_text
    assert "\\\\" not in persisted_text
    with sqlite3.connect(moved_sqlite) as sqlite_conn:
        payload_rows = sqlite_conn.execute("SELECT payload_json FROM evidence_blocks").fetchall()
    payload_text = "\n".join(row[0] for row in payload_rows)
    assert old_root_text not in payload_text
    assert "\\\\" not in payload_text

    quality = json.loads(_json_text(moved_doc_dir / "structure_quality.json"))
    assert quality["missing_retrieval_content_count"] == 0
    assert quality["overall_status"] in {"passed", "passed_with_warnings"}
