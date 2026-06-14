from __future__ import annotations

import json
import shutil
from pathlib import Path

from docagent.ingestion.quality import build_structure_quality_report
from docagent.parser.mineru_converter import build_page_blocks, content_list_to_blocks, find_content_list


def test_structure_quality_report_summarizes_real_schema_fixture(tmp_path: Path) -> None:
    mineru_dir = tmp_path / "mineru"
    shutil.copytree("tests/fixtures/mineru_real_schema", mineru_dir)
    (mineru_dir / "sample_origin.pdf").write_bytes(b"%PDF-1.4\n/Type /Page\n")
    document_dir = tmp_path / "document"
    document_dir.mkdir()
    (document_dir / "mineru_source_manifest.json").write_text(
        json.dumps({"mineru_batch_id": "batch1", "mineru_model_version": "vlm"}),
        encoding="utf-8",
    )
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n/Type /Page\n/Type /Page\nsource")
    content_list = find_content_list(mineru_dir)
    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=content_list)
    pages = build_page_blocks("doc123", blocks)

    report = build_structure_quality_report(
        doc_id="doc123",
        source_pdf=source,
        mineru_output_dir=mineru_dir,
        document_dir=document_dir,
        blocks=blocks,
        page_blocks=pages,
    )

    assert report["batch_id"] == "batch1"
    assert report["mineru_model"] == "vlm"
    assert report["mineru_backend"] == "vlm"
    assert report["layout_page_count"] == 2
    assert report["source_pdf_page_count"] == 2
    assert report["raw_block_count"] == 6
    assert report["converted_block_count"] == 6
    assert report["raw_type_distribution"]["chart"] == 1
    assert report["boilerplate_count"] == 3
    assert report["table_count"] == 1
    assert report["table_html_count"] == 1
    assert report["chart_count"] == 1
    assert report["image_reference_count"] == 2
    assert report["missing_image_reference_count"] == 0
    assert report["block_id_unique"] is True
    assert report["reading_order_contiguous"] is True
    assert report["adjacency_valid"] is True
    assert "mineru_origin_pdf_sha256_differs_from_source_pdf" in report["warnings"]
    assert report["overall_status"] == "passed_with_warnings"
    json.dumps(report, ensure_ascii=False)
