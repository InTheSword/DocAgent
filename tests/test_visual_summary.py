from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.tools.visual_summary import enhance_visual_blocks, visual_observation_for_block


class FakeVLMClient:
    def __init__(self) -> None:
        self.config = SimpleNamespace(model="fake-vlm")
        self.summary_calls = 0
        self.question_calls = 0

    def summarize_image(self, *, image_path: str | Path, context: str = "") -> dict:
        self.summary_calls += 1
        return {
            "image_kind": "chart",
            "caption": "Figure 1. Revenue chart.",
            "visual_summary": "The chart shows FY2020 revenue increasing to 45%.",
            "key_text": ["FY2020", "45%"],
            "confidence": 0.9,
            "should_index": True,
        }

    def answer_image_question(self, *, image_path: str | Path, question: str, context: str = "") -> dict:
        self.question_calls += 1
        return {
            "answer": "FY2020 reaches 45%.",
            "reasoning_summary": "The chart label shows 45% for FY2020.",
            "visual_summary": "The chart compares yearly percentages.",
            "confidence": 0.9,
            "support_status": "supported",
        }


def _block(
    block_id: str,
    *,
    block_type: str = "text",
    text: str = "",
    image_path: str | None = None,
    order: int = 1,
) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc1",
        block_id=block_id,
        block_type=block_type,
        text=text,
        page_id=1,
        image_path=image_path,
        location=EvidenceLocation(page=1, block_id=block_id),
        metadata={"reading_order": order},
    )


def test_enhance_visual_blocks_attaches_adjacent_caption(tmp_path: Path) -> None:
    caption = _block("caption", text="Figure 1. Revenue by year.", order=1)
    image = _block("image", block_type="image", image_path="images/chart.png", order=2)
    caption.metadata["next_block_id"] = image.block_id
    image.metadata["previous_block_id"] = caption.block_id
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "chart.png").write_bytes(b"fake-image")

    result = enhance_visual_blocks([caption, image], document_dir=tmp_path, mode="caption")

    assert result.native_caption_attached_count == 1
    assert image.metadata["caption"] == "Figure 1. Revenue by year."
    assert "Figure 1. Revenue by year." in image.retrieval_text
    assert image.metadata["visual_content_status"] == "caption_only"
    assert image.metadata["requires_visual_understanding"] is True


def test_enhance_visual_blocks_uses_vlm_and_cache(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "chart.png").write_bytes(b"fake-image")
    image = _block("image", block_type="image", image_path="images/chart.png", order=1)
    image.metadata["visual_content_status"] = "resource_only"
    image.metadata["requires_visual_understanding"] = True
    client = FakeVLMClient()

    first = enhance_visual_blocks([image], document_dir=tmp_path, mode="auto", client=client)

    assert first.used_vlm is True
    assert first.vlm_summary_count == 1
    assert client.summary_calls == 1
    assert image.visual_summary == "The chart shows FY2020 revenue increasing to 45%."
    assert image.metadata["visual_content_status"] == "vlm_summarized"
    assert image.metadata["requires_visual_understanding"] is False
    assert (tmp_path / "visual_summaries.jsonl").is_file()

    cached_image = _block("image2", block_type="image", image_path="images/chart.png", order=1)
    cached_image.metadata["visual_content_status"] = "resource_only"
    cached_image.metadata["requires_visual_understanding"] = True
    second = enhance_visual_blocks([cached_image], document_dir=tmp_path, mode="auto", client=client)

    assert second.cache_hit_count == 1
    assert client.summary_calls == 1
    assert cached_image.visual_summary == image.visual_summary


def test_visual_observation_for_block_returns_tool_observation(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "chart.png").write_bytes(b"fake-image")
    image = _block("image", block_type="image", image_path="images/chart.png", order=1)
    client = FakeVLMClient()

    result = visual_observation_for_block(
        image,
        "What does the chart show for FY2020?",
        mode="force",
        document_dir=tmp_path,
        client=client,
    )

    assert result["status"] == "success"
    assert result["tool"] == "visual_review"
    assert result["answer"] == "FY2020 reaches 45%."
    assert result["citations"][0]["block_id"] == "image"
    assert result["structured_result"]["used_vlm"] is True
    assert client.question_calls == 1
