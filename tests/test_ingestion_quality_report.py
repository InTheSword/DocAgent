from __future__ import annotations

import json
import shutil
from pathlib import Path

from docagent.ingestion.quality import build_structure_quality_report
from docagent.parser.mineru_converter import build_page_blocks, content_list_to_blocks, find_content_list


def test_structure_quality_report_summarizes_real_schema_fixture(tmp_path: Path) -> None:
    document_dir = tmp_path / "document"
    source_dir = document_dir / "source"
    source_dir.mkdir(parents=True)
    mineru_dir = document_dir / "mineru"
    shutil.copytree("tests/fixtures/mineru_real_schema", mineru_dir)
    (mineru_dir / "sample_origin.pdf").write_bytes(b"%PDF-1.4\n/Type /Page\n")
    (document_dir / "mineru_source_manifest.json").write_text(
        json.dumps({"mineru_batch_id": "batch1", "mineru_model_version": "vlm"}),
        encoding="utf-8",
    )
    source = source_dir / "original.pdf"
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
    assert report["source_pdf"]["path"] == "source/original.pdf"
    assert report["mineru_origin_pdf"]["path"] == "mineru/sample_origin.pdf"
    assert report["content_list_file"] == "mineru/sample_content_list.json"
    assert report["mineru_output_ordinary_content_list_count"] == 1
    assert report["mineru_output_content_list_v2_count"] == 1
    assert report["mineru_output_markdown_file_count"] == 0
    assert report["mineru_output_layout_json_count"] == 1
    assert report["mineru_output_image_resource_count"] == 1
    assert report["mineru_output_table_image_resource_count"] == 1
    assert report["mineru_output_inventory"]["file_count"] >= 6
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
    assert report["structured_table_count"] == 1
    assert report["chart_count"] == 1
    assert report["visual_relation_count"] == 1
    assert report["image_reference_count"] == 2
    assert report["missing_image_reference_count"] == 0
    assert report["missing_retrieval_content_count"] == 0
    assert report["indexable_chunk_count"] == 3
    assert report["non_indexable_chunk_count"] == 3
    assert report["empty_retrieval_chunk_rate"] == 0.0
    assert report["traceability_rate"] == 1.0
    assert report["chunk_strategy_counts"] == {"mineru_block_identity": 6}
    assert report["cross_page_chunk_count"] == 0
    assert report["sentence_split_chunk_count"] == 0
    assert report["chunk_contract_valid"] is True
    assert report["chunk_contract_error_count"] == 0
    assert report["empty_boilerplate_count"] == 0
    assert report["block_id_unique"] is True
    assert report["reading_order_contiguous"] is True
    assert report["reading_order_valid"] is True
    assert report["adjacency_valid"] is True
    assert "mineru_origin_pdf_sha256_differs_from_source_pdf" in report["warnings"]
    assert report["overall_status"] == "passed_with_warnings"
    json.dumps(report, ensure_ascii=False)


def test_structure_quality_report_counts_split_table_parent_and_children(tmp_path: Path) -> None:
    document_dir = tmp_path / "document"
    mineru_dir = document_dir / "mineru"
    mineru_dir.mkdir(parents=True)
    source = document_dir / "original.pdf"
    source.write_bytes(b"%PDF-1.4\n/Type /Page\n")
    content_list = mineru_dir / "sample_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "table",
                    "page_idx": 0,
                    "table_caption": "Table 1 Regional results",
                    "headers": ["Region", "Revenue"],
                    "rows": [[f"R{index}", str(index)] for index in range(1, 14)],
                }
            ]
        ),
        encoding="utf-8",
    )
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

    assert report["table_count"] == 1
    assert report["table_chunk_count"] == 3
    assert report["split_table_parent_count"] == 1
    assert report["table_retrieval_child_count"] == 2
    assert report["structured_table_count"] == 1
    assert report["indexable_chunk_count"] == 2
    assert report["chunk_contract_valid"] is True
    assert report["reading_order_contiguous"] is True
    assert report["reading_order_valid"] is True


def test_structure_quality_report_distinguishes_remote_and_missing_local_resources(tmp_path: Path) -> None:
    document_dir = tmp_path / "document"
    mineru_dir = document_dir / "mineru"
    mineru_dir.mkdir(parents=True)
    source = document_dir / "original.pdf"
    source.write_bytes(b"%PDF-1.4\n/Type /Page\n")
    (mineru_dir / "sample_content_list.json").write_text(
        json.dumps(
            [
                {
                    "type": "table",
                    "page_idx": 0,
                    "table_text": "Budget Estimate $100,000",
                    "table_image_url": "https://mineru.example/assets/table.png",
                },
                {
                    "type": "image",
                    "page_idx": 0,
                    "caption": "Missing local chart",
                    "image_path": "images/missing-chart.png",
                },
            ]
        ),
        encoding="utf-8",
    )
    blocks = content_list_to_blocks(
        doc_id="doc123",
        content_list_path=mineru_dir / "sample_content_list.json",
        document_dir=document_dir,
        resource_root=mineru_dir,
    )
    pages = build_page_blocks("doc123", blocks)

    report = build_structure_quality_report(
        doc_id="doc123",
        source_pdf=source,
        mineru_output_dir=mineru_dir,
        document_dir=document_dir,
        blocks=blocks,
        page_blocks=pages,
    )

    assert blocks[0].metadata["resource_is_remote"] is True
    assert blocks[0].metadata["resource_exists"] is None
    assert blocks[1].metadata["resource_exists"] is False
    assert report["image_reference_count"] == 2
    assert report["missing_image_reference_count"] == 1
    assert report["missing_image_reference_block_ids"] == [blocks[1].block_id]
    assert report["mineru_output_ordinary_content_list_count"] == 1
    assert report["mineru_output_inventory"]["category_counts"]["ordinary_content_list"] == 1
    assert "missing_image_references" in report["warnings"]


def test_structure_quality_report_supports_current_api_manifest_and_sparse_raw_order(tmp_path: Path) -> None:
    document_dir = tmp_path / "document"
    mineru_dir = document_dir / "mineru"
    mineru_dir.mkdir(parents=True)
    source = document_dir / "original.pdf"
    source.write_bytes(b"%PDF-1.4\n/Type /Page\n")
    (mineru_dir / "mineru_api_manifest.json").write_text(
        json.dumps({"batch_id": "batch-current", "model_version": "vlm"}),
        encoding="utf-8",
    )
    (mineru_dir / "sample_content_list.json").write_text(
        json.dumps(
            [
                {"type": "text", "page_idx": 0, "text": "Main paragraph", "bbox": [1, 2, 3, 4]},
                {"type": "text", "page_idx": 0, "text": "", "bbox": [1, 5, 3, 6]},
                {"type": "equation", "page_idx": 0, "text": "x = 1", "bbox": [1, 7, 3, 8]},
                {"type": "ref_text", "page_idx": 0, "text": "[1] Reference", "bbox": [1, 9, 3, 10]},
                {
                    "type": "page_footnote",
                    "page_idx": 0,
                    "text": "Corresponding author",
                    "bbox": [1, 11, 3, 12],
                },
            ]
        ),
        encoding="utf-8",
    )
    blocks = content_list_to_blocks(
        doc_id="doc123",
        content_list_path=mineru_dir / "sample_content_list.json",
        document_dir=document_dir,
        resource_root=mineru_dir,
    )
    pages = build_page_blocks("doc123", blocks)

    report = build_structure_quality_report(
        doc_id="doc123",
        source_pdf=source,
        mineru_output_dir=mineru_dir,
        document_dir=document_dir,
        blocks=blocks,
        page_blocks=pages,
    )

    assert report["batch_id"] == "batch-current"
    assert report["mineru_model"] == "vlm"
    assert report["mineru_manifest_path"] == "mineru/mineru_api_manifest.json"
    assert report["unknown_raw_types"] == []
    assert "unknown_raw_types_present" not in report["warnings"]
    assert report["reading_order_contiguous"] is False
    assert report["reading_order_valid"] is True
    assert "invalid_reading_order" not in report["warnings"]
