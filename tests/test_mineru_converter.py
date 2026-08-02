from __future__ import annotations

import json
from pathlib import Path

import shutil

import pytest

from docagent.parser.mineru_converter import (
    build_page_blocks,
    content_list_to_chunks,
    content_list_to_blocks,
    find_content_list,
    normalize_blocks,
    validate_mineru_chunk_contract,
)
from docagent.parser.run_mineru_parse import content_list_to_blocks as legacy_content_list_to_blocks
from docagent.schemas import EvidenceBlock, EvidenceLocation


def test_mineru_content_list_to_blocks_handles_text_table_image(tmp_path: Path) -> None:
    content = [
        {"type": "text", "page_idx": 0, "text": "Invoice Date: March 12, 2020", "bbox": [1, 2, 3, 4]},
        {"type": "table", "page_idx": 1, "table_text": "Year Revenue 2020 1280", "table_body": "<table></table>"},
        {
            "type": "image",
            "page_idx": 2,
            "caption": "Revenue chart",
            "nearby_text": ["FY2020 revenue was $100,000"],
            "image_path": "figures/chart.png",
        },
        {"type": "equation", "page_idx": 2, "text": "preserved unknown"},
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)
    pages = build_page_blocks("doc123", blocks)

    assert [block.block_type for block in blocks] == ["text", "table", "image", "text"]
    assert blocks[0].block_id == "doc123_p001_b0001"
    assert blocks[0].page_id == 1
    assert blocks[0].metadata["mineru_page_idx"] == 0
    assert blocks[0].location.bbox == [1.0, 2.0, 3.0, 4.0]
    assert blocks[1].table_html == "<table></table>"
    assert blocks[2].metadata["source_resource_path"] == "figures/chart.png"
    assert blocks[2].image_path == "figures/chart.png"
    assert blocks[2].metadata["image_caption"] == "Revenue chart"
    assert blocks[2].metadata["nearby_text"] == "FY2020 revenue was $100,000"
    assert blocks[2].metadata["visual_content_status"] == "ocr_or_nearby_text"
    assert blocks[2].metadata["visual_text_sources"] == ["caption", "nearby_text"]
    assert blocks[2].metadata["requires_visual_understanding"] is False
    assert "FY2020 revenue was $100,000" in blocks[2].retrieval_text
    assert "normalized_resource_path" not in blocks[2].metadata
    assert "source_content_list" not in blocks[2].metadata
    assert "unknown_raw_type" not in blocks[3].metadata
    assert blocks[0].metadata.get("next_block_id") is None
    assert blocks[0].metadata["next_document_block_id"] == blocks[1].block_id
    assert blocks[1].metadata.get("previous_block_id") is None
    assert blocks[1].metadata["previous_document_block_id"] == blocks[0].block_id
    assert [page.page_id for page in pages] == [1, 2, 3]


def test_legacy_mineru_converter_entry_uses_the_canonical_chunk_pipeline(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps([{"type": "text", "page_idx": 0, "text": "Canonical content."}]),
        encoding="utf-8",
    )

    canonical = content_list_to_chunks(doc_id="doc123", content_list_path=path)
    legacy = legacy_content_list_to_blocks("doc123", path)

    assert [chunk.to_dict() for chunk in legacy] == [chunk.to_dict() for chunk in canonical]


def test_mineru_blocks_are_identity_chunks_by_default(tmp_path: Path) -> None:
    content = [
        {"type": "text", "page_idx": 0, "text": "Short heading"},
        {"type": "text", "page_idx": 0, "text": "Short paragraph"},
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)

    assert [block.text for block in blocks] == ["Short heading", "Short paragraph"]
    assert all(block.metadata["chunk_strategy"] == "mineru_block_identity" for block in blocks)
    assert [block.metadata["source_block_ids"] for block in blocks] == [
        ["doc123_p001_b0001"],
        ["doc123_p001_b0002"],
    ]


def test_mineru_chunks_receive_hierarchy_page_and_hash_metadata(tmp_path: Path) -> None:
    content = [
        {"type": "text", "page_idx": 0, "text_level": 1, "text": "Annual Report"},
        {"type": "text", "page_idx": 0, "text": "Opening paragraph"},
        {"type": "text", "page_idx": 1, "text_level": 2, "text": "Revenue"},
        {"type": "text", "page_idx": 1, "text": "Revenue increased by 20%."},
        {"type": "page_number", "page_idx": 1, "text": "7"},
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    first = content_list_to_blocks(doc_id="doc123", content_list_path=path)
    second = content_list_to_blocks(doc_id="doc123", content_list_path=path)

    title, opening, section, body, page_number = first
    assert title.metadata["content_type"] == "heading"
    assert title.metadata["heading_level"] == 1
    assert title.metadata["heading_role"] == "document_title"
    assert title.metadata["section_path"] == ["Annual Report"]
    assert opening.metadata["section_path"] == ["Annual Report"]
    assert opening.metadata["parent_heading_id"] == title.block_id
    assert section.metadata["heading_level"] == 2
    assert section.metadata["heading_role"] == "section_heading"
    assert section.metadata["section_path"] == ["Annual Report", "Revenue"]
    assert body.metadata["section_path"] == ["Annual Report", "Revenue"]
    assert body.metadata["document_page_index"] == 1
    assert body.metadata["document_page_number"] == 2
    assert body.metadata["printed_page_number"] == "7"
    assert body.metadata["global_chunk_id"] == body.block_id
    assert len(body.metadata["content_hash"]) == 64
    assert len(body.metadata["source_item_hash"]) == 64
    assert body.metadata["feature_tags"] == ["content_type:body", "modality:text"]
    assert page_number.metadata["content_type"] == "page_number"
    assert page_number.metadata["is_boilerplate"] is True
    assert "[Section: Annual Report > Revenue]" in body.retrieval_text
    assert "[Type: body]" in body.retrieval_text
    assert [block.metadata["content_hash"] for block in first] == [
        block.metadata["content_hash"] for block in second
    ]
    assert validate_mineru_chunk_contract(first) == {}


def test_cross_page_text_is_merged_before_sentence_aware_splitting(tmp_path: Path) -> None:
    content = [
        {
            "id": "part-1",
            "type": "text",
            "page_idx": 0,
            "text": "The analysis continues across the physical page boundary without a terminal mark",
        },
        {
            "id": "part-2",
            "type": "text",
            "page_idx": 1,
            "text": "and concludes with a complete sentence. A second sentence keeps the semantic unit intact.",
        },
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    chunks = content_list_to_chunks(
        doc_id="doc123",
        content_list_path=path,
        split_max_chars=80,
    )
    pages = build_page_blocks("doc123", chunks)

    assert len(chunks) == 3
    assert all(chunk.metadata["chunk_strategy"] == "cross_page_sentence_split" for chunk in chunks)
    assert all(chunk.metadata["source_page_numbers"] == [1, 2] for chunk in chunks)
    assert all(chunk.metadata["source_item_ids"] == ["part-1", "part-2"] for chunk in chunks)
    assert all(chunk.metadata["document_page_number_start"] == 1 for chunk in chunks)
    assert all(chunk.metadata["document_page_number_end"] == 2 for chunk in chunks)
    assert all(len(chunk.text) <= 80 for chunk in chunks)
    assert [page.page_id for page in pages] == [1, 2]
    assert all(chunks[0].block_id in page.metadata["child_block_ids"] for page in pages)
    assert validate_mineru_chunk_contract(chunks) == {}


def test_cross_page_text_with_terminal_sentence_is_not_merged(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps(
            [
                {"type": "text", "page_idx": 0, "text": "The first page ends here."},
                {"type": "text", "page_idx": 1, "text": "A new paragraph starts here."},
            ]
        ),
        encoding="utf-8",
    )

    chunks = content_list_to_chunks(doc_id="doc123", content_list_path=path)

    assert len(chunks) == 2
    assert all(chunk.metadata["chunk_strategy"] == "mineru_block_identity" for chunk in chunks)


def test_short_page_text_is_not_treated_as_cross_page_continuation(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps(
            [
                {"type": "text", "page_idx": 0, "text": "content for page 1"},
                {"type": "text", "page_idx": 1, "text": "content for page 2"},
            ]
        ),
        encoding="utf-8",
    )

    chunks = content_list_to_chunks(doc_id="doc123", content_list_path=path)

    assert [chunk.page_id for chunk in chunks] == [1, 2]
    assert all(chunk.metadata["chunk_strategy"] == "mineru_block_identity" for chunk in chunks)


def test_page_boundary_geometry_can_confirm_cross_page_continuation(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "page_idx": 0,
                    "text": "这是一段位于页面底部并且在下一页继续展开的正文内容没有结束标点",
                    "bbox": [10, 760, 590, 790],
                },
                {
                    "type": "text",
                    "page_idx": 1,
                    "text": "下一页顶部继续给出其余内容并在这里结束。",
                    "bbox": [10, 10, 590, 60],
                },
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "layout.json").write_text(
        json.dumps(
            {
                "pdf_info": [
                    {"page_idx": 0, "page_size": [600, 800]},
                    {"page_idx": 1, "page_size": [600, 800]},
                ]
            }
        ),
        encoding="utf-8",
    )

    chunks = content_list_to_chunks(doc_id="doc123", content_list_path=path)

    assert len(chunks) == 1
    assert chunks[0].metadata["chunk_strategy"] == "cross_page_merge"
    assert chunks[0].metadata["source_page_numbers"] == [1, 2]


def test_mineru_chunks_preserve_table_layout_and_visual_relations(tmp_path: Path) -> None:
    content = [
        {"id": "raw-title", "type": "text", "page_idx": 0, "text_level": 1, "text": "Annual Report"},
        {"id": "raw-body", "type": "text", "page_idx": 0, "text": "The following figure summarizes revenue."},
        {"id": "raw-image", "type": "image", "page_idx": 0, "img_path": "figure.png"},
        {"id": "raw-caption", "type": "caption", "page_idx": 0, "text": "Figure 1 Revenue trend"},
        {
            "id": "raw-table",
            "type": "table",
            "page_idx": 0,
            "table_body": (
                "<table><tr><th>Year</th><th>Revenue</th></tr>"
                "<tr><td>2023</td><td>130</td></tr></table>"
            ),
        },
        {"id": "raw-next-page", "type": "text", "page_idx": 1, "text": "Second page."},
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    (tmp_path / "layout.json").write_text(
        json.dumps(
            {
                "pdf_info": [
                    {"page_idx": 0, "page_size": [1000, 800]},
                    {"page_idx": 1, "page_size": [1200, 900]},
                ]
            }
        ),
        encoding="utf-8",
    )

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)
    _title, body, image, caption, table, next_page = blocks

    assert body.metadata["source_item_id"] == "raw-body"
    assert body.metadata["page_width"] == 1000.0
    assert body.metadata["page_height"] == 800.0
    assert [block.metadata["page_reading_order"] for block in blocks] == [1, 2, 3, 4, 5, 1]
    assert image.metadata["caption_block_ids"] == [caption.block_id]
    assert caption.metadata["related_block_id"] == image.block_id
    assert body.block_id in image.metadata["nearby_block_ids"]
    assert table.metadata["table_headers"] == ["Year", "Revenue"]
    assert table.metadata["table_rows"] == [["2023", "130"]]
    assert table.metadata["row_count"] == 1
    assert table.metadata["column_count"] == 2
    assert table.metadata["feature_tags"] == [
        "content_type:table",
        "modality:table",
        "has_table_structure",
    ]
    assert table.metadata["next_block_id"] is None
    assert table.metadata["next_document_block_id"] == next_page.block_id
    assert next_page.metadata["previous_block_id"] is None
    assert next_page.metadata["previous_document_block_id"] == table.block_id
    assert validate_mineru_chunk_contract(blocks) == {}


def test_table_html_infers_td_headers_and_expands_rowspan_colspan(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps(
            [
                {
                    "type": "table",
                    "page_idx": 0,
                    "table_body": (
                        '<table><tr><td rowspan="2">Model</td><td colspan="2">Score</td></tr>'
                        "<tr><td>Dev</td><td>Test</td></tr>"
                        "<tr><td>DocAgent</td><td>80</td><td>82</td></tr></table>"
                    ),
                }
            ]
        ),
        encoding="utf-8",
    )

    table = content_list_to_chunks(doc_id="doc123", content_list_path=path)[0]

    assert table.metadata["table_headers"] == ["Model", "Score Dev", "Score Test"]
    assert table.metadata["table_rows"] == [["DocAgent", "80", "82"]]
    assert table.metadata["table_markdown"].startswith("| Model | Score Dev | Score Test |")


def test_adjacent_captionless_table_receives_its_caption_from_combined_caption(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "table-14-data",
                    "type": "table",
                    "page_idx": 0,
                    "headers": ["Metric", "Static", "Dynamic"],
                    "rows": [["Calls", "15", "5.6"]],
                },
                {
                    "id": "table-15-data",
                    "type": "table",
                    "page_idx": 0,
                    "table_caption": [
                        "Table 14. Static and dynamic generation efficiency.",
                        "Table 15. End-to-end inference efficiency.",
                    ],
                    "headers": ["Method", "Time"],
                    "rows": [["DocAgent", "38.2"]],
                },
            ]
        ),
        encoding="utf-8",
    )

    first, second = content_list_to_chunks(doc_id="doc123", content_list_path=path)

    assert first.metadata["table_caption"] == "Table 14. Static and dynamic generation efficiency."
    assert second.metadata["table_caption"] == "Table 15. End-to-end inference efficiency."
    assert first.metadata["table_caption_source_block_id"] == second.block_id
    assert second.metadata["table_caption_split"] is True
    assert "Table 14" in first.retrieval_text
    assert "Table 14" not in second.retrieval_text
    assert "Table 14" not in second.metadata.get("table_context", "")


def test_adjacent_explicit_table_caption_is_copied_to_table(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "table-caption",
                    "type": "caption",
                    "page_idx": 0,
                    "text": "Table 1. Regional results.",
                },
                {
                    "id": "table-data",
                    "type": "table",
                    "page_idx": 0,
                    "headers": ["Region", "Revenue"],
                    "rows": [["East", "120"]],
                },
            ]
        ),
        encoding="utf-8",
    )

    caption, table = content_list_to_chunks(doc_id="doc123", content_list_path=path)

    assert table.metadata["table_caption"] == caption.text
    assert table.metadata["table_caption_source_block_id"] == caption.block_id
    assert caption.metadata["related_block_id"] == table.block_id
    assert caption.text in table.retrieval_text


def test_large_table_builds_structured_parent_and_row_group_children(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "large-table",
                    "type": "table",
                    "page_idx": 0,
                    "table_caption": "Table 1 Regional results",
                    "table_unit": "USD million",
                    "headers": ["Region", "Revenue"],
                    "rows": [[f"R{index}", str(index)] for index in range(1, 14)],
                }
            ]
        ),
        encoding="utf-8",
    )

    first = content_list_to_chunks(doc_id="doc123", content_list_path=path)
    second = content_list_to_chunks(doc_id="doc123", content_list_path=path)
    parent, child_one, child_two = first

    assert [chunk.block_id for chunk in first] == [chunk.block_id for chunk in second]
    assert parent.metadata["table_role"] == "structured_parent"
    assert parent.metadata["exclude_from_retrieval"] is True
    assert parent.metadata["include_in_structured_table_index"] is True
    assert parent.is_indexable is False
    assert parent.metadata["child_block_ids"] == [child_one.block_id, child_two.block_id]
    assert [child_one.metadata["row_start"], child_one.metadata["row_end"]] == [1, 12]
    assert [child_two.metadata["row_start"], child_two.metadata["row_end"]] == [13, 13]
    assert child_one.metadata["table_headers"] == ["Region", "Revenue"]
    assert child_two.metadata["table_caption"] == "Table 1 Regional results"
    assert child_two.metadata["table_unit"] == "USD million"
    assert all(child.metadata["table_parent_id"] == parent.block_id for child in first[1:])
    assert all(child.metadata["table_role"] == "retrieval_child" for child in first[1:])
    assert all(child.metadata["include_in_structured_table_index"] is False for child in first[1:])
    assert all(child.is_indexable for child in first[1:])
    assert validate_mineru_chunk_contract(first) == {}


def test_wide_table_splits_on_markdown_size_even_with_few_rows(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps(
            [
                {
                    "type": "table",
                    "page_idx": 0,
                    "headers": ["Item", "Description"],
                    "rows": [
                        ["A", "a" * 1000],
                        ["B", "b" * 1000],
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    parent, first_child, second_child = content_list_to_chunks(
        doc_id="doc123",
        content_list_path=path,
    )

    assert parent.metadata["table_role"] == "structured_parent"
    assert first_child.metadata["table_rows"][0][0] == "A"
    assert second_child.metadata["table_rows"][0][0] == "B"
    assert all(len(child.metadata["table_markdown"]) <= 1800 for child in (first_child, second_child))


def test_small_table_remains_a_single_retrieval_and_structured_chunk(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps(
            [
                {
                    "type": "table",
                    "page_idx": 0,
                    "headers": ["Year", "Revenue"],
                    "rows": [["2025", "130"]],
                }
            ]
        ),
        encoding="utf-8",
    )

    chunks = content_list_to_chunks(doc_id="doc123", content_list_path=path)

    assert len(chunks) == 1
    assert chunks[0].metadata["table_role"] == "identity"
    assert chunks[0].metadata["include_in_structured_table_index"] is True
    assert chunks[0].is_indexable is True


def test_page_aggregate_is_context_only_not_a_retrieval_chunk(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list.json"
    path.write_text(
        json.dumps([{"type": "text", "page_idx": 0, "text": "Invoice date"}]),
        encoding="utf-8",
    )

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)
    pages = build_page_blocks("doc123", blocks)

    assert pages[0].text
    assert pages[0].metadata["content_type"] == "page_aggregate"
    assert pages[0].metadata["exclude_from_retrieval"] is True
    assert pages[0].is_indexable is False


def test_mineru_current_textual_types_are_not_marked_unknown(tmp_path: Path) -> None:
    content = [
        {"type": "equation", "page_idx": 0, "text": "x = 1"},
        {"type": "ref_text", "page_idx": 0, "text": "[1] Reference"},
        {"type": "page_footnote", "page_idx": 0, "text": "Corresponding author"},
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)

    assert len(blocks) == 3
    assert all("unknown_raw_type" not in block.metadata for block in blocks)


def test_normalize_blocks_does_not_merge_mineru_chunks_by_default() -> None:
    blocks = [
        EvidenceBlock(
            doc_id="doc123",
            block_id=f"b{index}",
            block_type="text",
            text=text,
            page_id=1,
            location=EvidenceLocation(page=1, block_id=f"b{index}"),
            metadata={
                "chunk_strategy": "mineru_block_identity",
                "source_block_ids": [f"b{index}"],
            },
        )
        for index, text in enumerate(["Short heading", "Short paragraph"], start=1)
    ]

    normalized = normalize_blocks(blocks)

    assert [block.block_id for block in normalized] == ["b1", "b2"]
    assert [block.text for block in normalized] == ["Short heading", "Short paragraph"]


def test_mineru_content_list_to_blocks_preserves_secondary_text_fields(tmp_path: Path) -> None:
    content = [
        {
            "type": "text",
            "page_idx": 0,
            "text": [{"text": "Budget"}, {"content": "Estimate"}],
            "content": "$100,000",
        },
        {
            "type": "image",
            "page_idx": 0,
            "caption": "Figure 1",
            "content": "Budget Estimate $100,000",
        },
        {
            "type": "table",
            "page_idx": 0,
            "content": "Budget table",
            "table_body": "<table><tr><td>Budget Estimate</td><td>$100,000</td></tr></table>",
        },
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)
    pages = build_page_blocks("doc123", blocks)
    page_text = pages[0].text

    assert "Budget Estimate" in blocks[0].text
    assert "$100,000" in blocks[0].text
    assert "Figure 1" in blocks[1].text
    assert "$100,000" in blocks[1].text
    assert "Budget table" in blocks[2].text
    assert "$100,000" in page_text


def test_mineru_image_blocks_mark_visual_readiness(tmp_path: Path) -> None:
    content = [
        {
            "type": "image",
            "page_idx": 0,
            "image_path": "figures/diagram.png",
        },
        {
            "type": "figure",
            "page_idx": 0,
            "image_path": "figures/flow.png",
            "visual_summary": "Flow chart shows the approval sequence.",
        },
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)

    assert [block.block_type for block in blocks] == ["image", "image"]
    assert blocks[0].text == ""
    assert blocks[0].retrieval_text == ""
    assert blocks[0].metadata["visual_content_status"] == "resource_only"
    assert blocks[0].metadata["visual_text_sources"] == []
    assert blocks[0].metadata["requires_visual_understanding"] is True
    assert blocks[1].visual_summary == "Flow chart shows the approval sequence."
    assert "Flow chart shows the approval sequence." in blocks[1].retrieval_text
    assert blocks[1].metadata["visual_content_status"] == "vlm_summarized"
    assert blocks[1].metadata["visual_text_sources"] == ["visual_summary"]
    assert blocks[1].metadata["requires_visual_understanding"] is False


def test_mineru_content_list_to_blocks_preserves_remote_and_table_image_resources(tmp_path: Path) -> None:
    content = [
        {
            "type": "table",
            "page_idx": 0,
            "table_text": "Budget Estimate $100,000",
            "table_body": "<table><tr><td>Budget Estimate</td><td>$100,000</td></tr></table>",
            "table_image_url": "https://mineru.example/assets/table.png",
        },
        {
            "type": "image",
            "page_idx": 0,
            "caption": "Program chart",
            "image_url": "https://mineru.example/assets/chart.png",
        },
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)

    assert blocks[0].block_type == "table"
    assert blocks[0].image_path == "https://mineru.example/assets/table.png"
    assert blocks[0].metadata["resource_key"] == "table_image_url"
    assert blocks[0].metadata["resource_is_remote"] is True
    assert blocks[0].metadata["resource_exists"] is None
    assert blocks[1].block_type == "image"
    assert blocks[1].image_path == "https://mineru.example/assets/chart.png"
    assert blocks[1].metadata["resource_key"] == "image_url"
    assert blocks[1].metadata["resource_is_remote"] is True
    assert blocks[1].metadata["resource_exists"] is None


def test_mineru_content_list_to_blocks_preserves_nested_unknown_text_fields(tmp_path: Path) -> None:
    content = [
        {
            "type": "text",
            "page_idx": 0,
            "content": {
                "ocr_result": [
                    {"label": "Budget Estimate"},
                    {"raw_value": "$100,000"},
                ]
            },
        }
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)
    pages = build_page_blocks("doc123", blocks)

    assert "Budget Estimate" in blocks[0].text
    assert "$100,000" in blocks[0].text
    assert "$100,000" in pages[0].text


def test_mineru_content_list_to_blocks_keeps_substantive_boilerplate_typed_text(tmp_path: Path) -> None:
    content = [
        {"type": "footer", "page_idx": 0, "text": "Budget Estimate $100,000"},
        {"type": "page_number", "page_idx": 0, "text": "13"},
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)
    pages = build_page_blocks("doc123", blocks)

    assert blocks[0].metadata["raw_mineru_type"] == "footer"
    assert blocks[0].metadata["raw_boilerplate_type"] is True
    assert blocks[0].metadata["is_boilerplate"] is False
    assert blocks[0].metadata["exclude_from_retrieval"] is False
    assert "$100,000" in blocks[0].retrieval_text
    assert blocks[1].metadata["is_boilerplate"] is True
    assert blocks[1].retrieval_text == ""
    assert "$100,000" in pages[0].text
    assert "13" not in pages[0].text


def test_mineru_real_schema_preserves_boilerplate_chart_and_resources(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/mineru_real_schema")
    work = tmp_path / "mineru"
    shutil.copytree(fixture, work)

    content_list = find_content_list(work)
    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=content_list)

    assert content_list.name == "sample_content_list.json"
    assert len(blocks) == 6
    assert blocks[0].page_id == 1
    table = blocks[1]
    chart = blocks[2]
    assert table.block_type == "table"
    assert table.table_html.startswith("<table>")
    assert table.metadata["table_caption"] == "Table 1 Sample"
    assert table.metadata["table_markdown"].startswith("| Country | Value |")
    assert table.image_path == "mineru/images/table.jpg"
    assert table.metadata["resource_exists"] is True
    assert chart.block_type == "image"
    assert chart.image_path == "mineru/images/chart.jpg"
    assert chart.metadata["raw_mineru_type"] == "chart"
    assert chart.metadata["visual_subtype"] == "bar"
    assert chart.metadata["resource_exists"] is True
    assert chart.visual_summary == "| Country | Value | | A | 1 |"
    assert chart.metadata["visual_content_status"] == "vlm_summarized"
    assert chart.metadata["visual_text_sources"] == ["visual_summary", "caption"]
    assert chart.metadata["requires_visual_understanding"] is False
    assert [block.metadata["raw_boilerplate_type"] for block in blocks[3:]] == [True, True, True]
    assert [block.metadata["is_boilerplate"] for block in blocks[3:]] == [True, True, True]
    assert all(block.metadata["exclude_from_retrieval"] for block in blocks[3:])
    assert all(block.retrieval_text == "" for block in blocks[3:])
    assert all("normalized_resource_path" not in block.metadata for block in blocks)
    assert all("source_content_list" not in block.metadata for block in blocks)
    assert blocks[-1].metadata["previous_block_id"] == blocks[-2].block_id


def test_find_content_list_accepts_v2_when_ordinary_list_is_absent(tmp_path: Path) -> None:
    v2 = tmp_path / "only_content_list_v2.json"
    v2.write_text("[]", encoding="utf-8")

    assert find_content_list(tmp_path) == v2


def test_find_content_list_prefers_ordinary_list_over_v2(tmp_path: Path) -> None:
    v2 = tmp_path / "only_content_list_v2.json"
    ordinary = tmp_path / "sample_content_list.json"
    v2.write_text("[]", encoding="utf-8")
    ordinary.write_text("[]", encoding="utf-8")

    assert find_content_list(tmp_path) == ordinary


def test_find_content_list_rejects_missing_or_multiple_lists(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="content-list"):
        find_content_list(tmp_path)

    (tmp_path / "a_content_list.json").write_text("[]", encoding="utf-8")
    (tmp_path / "b_content_list.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="multiple ordinary"):
        find_content_list(tmp_path)

    for path in tmp_path.glob("*content_list.json"):
        path.unlink()
    (tmp_path / "a_content_list_v2.json").write_text("[]", encoding="utf-8")
    (tmp_path / "b_content_list_v2.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="multiple MinerU content-list v2"):
        find_content_list(tmp_path)
