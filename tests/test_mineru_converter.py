from __future__ import annotations

import json
from pathlib import Path

import shutil

import pytest

from docagent.parser.mineru_converter import build_page_blocks, content_list_to_blocks, find_content_list


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
    assert blocks[2].metadata["img_path"] == "figures/chart.png"
    assert blocks[2].image_path == "figures/chart.png"
    assert blocks[2].metadata["caption"] == "Revenue chart"
    assert blocks[2].metadata["nearby_text"] == ["FY2020 revenue was $100,000"]
    assert "FY2020 revenue was $100,000" in blocks[2].retrieval_text
    assert "normalized_resource_path" not in blocks[2].metadata
    assert "source_content_list" not in blocks[2].metadata
    assert blocks[3].metadata["unknown_raw_type"] is True
    assert blocks[0].metadata["next_block_id"] == blocks[1].block_id
    assert blocks[1].metadata["previous_block_id"] == blocks[0].block_id
    assert [page.page_id for page in pages] == [1, 2, 3]


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
    assert table.metadata["table_caption"] == ["Table 1 Sample"]
    assert table.image_path == "mineru/images/table.jpg"
    assert table.metadata["resource_exists"] is True
    assert chart.block_type == "image"
    assert chart.image_path == "mineru/images/chart.jpg"
    assert chart.metadata["raw_mineru_type"] == "chart"
    assert chart.metadata["sub_type"] == "bar"
    assert chart.metadata["resource_exists"] is True
    assert [block.metadata["raw_boilerplate_type"] for block in blocks[3:]] == [True, True, True]
    assert [block.metadata["is_boilerplate"] for block in blocks[3:]] == [True, True, True]
    assert all(block.metadata["exclude_from_retrieval"] for block in blocks[3:])
    assert all(block.retrieval_text == "" for block in blocks[3:])
    assert all("normalized_resource_path" not in block.metadata for block in blocks)
    assert all("source_content_list" not in block.metadata for block in blocks)
    assert blocks[-1].metadata["previous_block_id"] == blocks[-2].block_id


def test_find_content_list_rejects_missing_or_multiple_ordinary_lists(tmp_path: Path) -> None:
    (tmp_path / "only_content_list_v2.json").write_text("[]", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="ordinary MinerU"):
        find_content_list(tmp_path)

    (tmp_path / "a_content_list.json").write_text("[]", encoding="utf-8")
    (tmp_path / "b_content_list.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="multiple ordinary"):
        find_content_list(tmp_path)
