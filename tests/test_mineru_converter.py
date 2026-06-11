from __future__ import annotations

import json
from pathlib import Path

from docagent.parser.mineru_converter import build_page_blocks, content_list_to_blocks


def test_mineru_content_list_to_blocks_handles_text_table_image(tmp_path: Path) -> None:
    content = [
        {"type": "text", "page_idx": 0, "text": "Invoice Date: March 12, 2020", "bbox": [1, 2, 3, 4]},
        {"type": "table", "page_idx": 1, "table_text": "Year Revenue 2020 1280", "table_body": "<table></table>"},
        {"type": "image", "page_idx": 2, "caption": "Revenue chart", "image_path": "figures/chart.png"},
        {"type": "equation", "page_idx": 2, "text": "ignored"},
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    blocks = content_list_to_blocks(doc_id="doc123", content_list_path=path)
    pages = build_page_blocks("doc123", blocks)

    assert [block.block_type for block in blocks] == ["text", "table", "image"]
    assert blocks[0].block_id == "doc123_p000_b0001"
    assert blocks[0].location.bbox == [1.0, 2.0, 3.0, 4.0]
    assert blocks[1].table_html == "<table></table>"
    assert blocks[2].image_path == "figures/chart.png"
    assert [page.page_id for page in pages] == [0, 1, 2]

