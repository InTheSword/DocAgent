from __future__ import annotations

import json
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.tools.document_tools import (
    count_blocks,
    count_images,
    count_pages,
    count_tables,
    get_page_text,
    list_pages,
)


def _repository_with_document(tmp_path: Path) -> DocumentRepository:
    conn = connect(tmp_path / "docagent.sqlite")
    repository = DocumentRepository(conn)
    repository.upsert_document(
        DocumentRecord(
            doc_id="doc1",
            sha256="a" * 64,
            original_name="sample.pdf",
            mime_type="application/pdf",
            file_size=123,
            file_path=str(tmp_path / "documents" / "doc1" / "source" / "original.pdf"),
            document_dir=str(tmp_path / "documents" / "doc1"),
            page_count=2,
            parser_backend="mineru_existing",
            parse_status="parsed",
            index_status="not_started",
        )
    )
    repository.save_evidence_blocks(
        [
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_page",
                block_type="page",
                text="Page one contains the invoice total and a compact table with service rows.",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_page"),
                metadata={"child_block_ids": ["doc1_p001_text", "doc1_p001_table"]},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p002_page",
                block_type="page",
                text="Page two contains one product image and one chart caption from MinerU OCR.",
                page_id=2,
                location=EvidenceLocation(page=2, block_id="doc1_p002_page"),
                metadata={"child_block_ids": ["doc1_p002_image", "doc1_p002_chart"]},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_text",
                block_type="text",
                text="Invoice Total: 42 USD",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_text"),
                metadata={"raw_mineru_type": "text"},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_table",
                block_type="table",
                text="Service Amount Hosting 42",
                table_html="<table><tr><td>Hosting</td><td>42</td></tr></table>",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_table", table_id="doc1_p001_table"),
                metadata={"raw_mineru_type": "table"},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p002_image",
                block_type="image",
                text="Product screenshot caption",
                image_path="images/product.png",
                page_id=2,
                location=EvidenceLocation(page=2, block_id="doc1_p002_image", image_id="doc1_p002_image"),
                metadata={"raw_mineru_type": "image", "resource_exists": True},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p002_chart",
                block_type="image",
                text="Quarterly revenue chart caption",
                image_path="images/chart.png",
                page_id=2,
                location=EvidenceLocation(page=2, block_id="doc1_p002_chart", image_id="doc1_p002_chart"),
                metadata={"raw_mineru_type": "chart", "resource_exists": True},
            ),
        ]
    )
    return repository


def test_count_pages_returns_document_page_count(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = count_pages(repository, "doc1")

    assert result["status"] == "success"
    assert result["page_count"] == 2
    assert result["source"] == "documents.page_count"


def test_count_blocks_returns_by_block_type(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = count_blocks(repository, "doc1")

    assert result["status"] == "success"
    assert result["block_count"] == 4
    assert result["by_block_type"] == {"image": 2, "table": 1, "text": 1}
    assert result["includes_page_blocks"] is False


def test_count_tables_returns_table_counts(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = count_tables(repository, "doc1")

    assert result["status"] == "success"
    assert result["table_count"] == 1
    assert result["table_html_count"] == 1
    assert result["tables"][0]["block_id"] == "doc1_p001_table"


def test_count_images_returns_image_and_chart_counts(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = count_images(repository, "doc1")

    assert result["status"] == "success"
    assert result["image_count"] == 2
    assert result["chart_count"] == 1
    assert result["by_raw_type"] == {"chart": 1, "image": 1}


def test_get_page_text_uses_one_based_page_numbers(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = get_page_text(repository, "doc1", 1, text_preview_chars=24)

    assert result["status"] == "success"
    assert result["page"] == 1
    assert "Page one contains" in result["text"]
    assert len(result["text_preview"]) <= 24
    assert result["truncated"] is True
    assert result["block_ids"] == ["doc1_p001_page"]
    assert result["page_block_id"] == "doc1_p001_page"
    assert result["child_block_ids"] == ["doc1_p001_text", "doc1_p001_table"]


def test_get_page_text_returns_structured_error_for_missing_page(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = get_page_text(repository, "doc1", 99)

    assert result["status"] == "error"
    assert result["error"]["code"] == "page_not_found"
    assert result["error"]["page"] == 99
    assert result["error"]["available_pages"] == [1, 2]


def test_list_pages_returns_page_previews(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = list_pages(repository, "doc1", text_preview_chars=18)

    assert result["status"] == "success"
    assert result["page_count"] == 2
    assert [page["page"] for page in result["pages"]] == [1, 2]
    assert result["pages"][0]["block_count"] == 2
    assert len(result["pages"][0]["text_preview"]) <= 18
    assert result["pages"][0]["page_block_id"] == "doc1_p001_page"


def test_missing_doc_id_returns_structured_error(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = count_pages(repository, "missing")

    assert result["status"] == "error"
    assert result["tool"] == "count_pages"
    assert result["doc_id"] == "missing"
    assert result["error"]["code"] == "document_not_found"


def test_tool_outputs_are_json_serializable(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    outputs = [
        count_pages(repository, "doc1"),
        count_blocks(repository, "doc1"),
        count_tables(repository, "doc1"),
        count_images(repository, "doc1"),
        get_page_text(repository, "doc1", 1),
        list_pages(repository, "doc1"),
        count_pages(repository, "missing"),
    ]

    for output in outputs:
        json.dumps(output)
