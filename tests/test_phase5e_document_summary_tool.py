from __future__ import annotations

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.tools.document_summary import summarize_document


class FixtureRepository:
    def __init__(self, blocks: list[object], *, page_count: int | None = 3) -> None:
        self.blocks = blocks
        self.page_count = page_count

    def get_document(self, doc_id: str) -> dict:
        return {"doc_id": doc_id, "page_count": self.page_count}

    def load_evidence_blocks(self, doc_id: str) -> list[object]:
        return self.blocks


def _block(page: int, index: int, text: str, *, block_type: str = "text") -> EvidenceBlock:
    block_id = f"doc1_p{page:03d}_b{index:03d}"
    return EvidenceBlock(
        doc_id="doc1",
        block_id=block_id,
        block_type=block_type,
        text=text,
        page_id=page,
        location=EvidenceLocation(page=page, block_id=block_id),
    )


def test_summarize_document_completed() -> None:
    repository = FixtureRepository(
        [
            _block(1, 1, "Annual Report Overview"),
            _block(1, 2, "The report explains revenue growth, customer activity, and operating priorities."),
            _block(2, 1, "The second page describes product launches and regional expansion plans."),
            _block(3, 1, "The conclusion highlights execution risks and next quarter focus areas."),
        ]
    )

    result = summarize_document(repository, "doc1", question="Summarize this document.")

    assert result["status"] == "completed"
    assert result["task_type"] == "document_summary"
    assert result["summary"] is not None
    assert result["summary"]["key_points"]
    assert result["summary"]["page_summaries"]
    assert result["citations"]
    assert result["trace"]["used_llm"] is False
    assert result["trace"]["used_vlm"] is False
    assert result["trace"]["used_training"] is False


def test_summary_citations_are_valid() -> None:
    blocks = [
        _block(1, 1, "Project Summary"),
        _block(1, 2, "DocAgent converts parsed document content into traceable evidence blocks."),
        {
            "doc_id": "doc1",
            "block_id": "doc1_p002_b001",
            "block_type": "text",
            "text": "The system returns structured summaries with page and block citations.",
            "page_id": 2,
            "location": {"page": 2, "block_id": "doc1_p002_b001"},
        },
    ]
    repository = FixtureRepository(blocks)

    result = summarize_document(repository, "doc1")

    valid_ids = {block.block_id if isinstance(block, EvidenceBlock) else block["block_id"] for block in blocks}
    assert result["citations"]
    assert {citation["block_id"] for citation in result["citations"]}.issubset(valid_ids)
    for point in result["summary"]["key_points"]:
        assert point["citations"]
        assert point["citations"][0]["block_id"] in valid_ids


def test_summary_is_bounded_by_max_pages() -> None:
    blocks = [_block(page, 1, f"Page {page} contains a useful summary paragraph for this long report.") for page in range(1, 11)]
    repository = FixtureRepository(blocks, page_count=10)

    result = summarize_document(repository, "doc1", max_pages=3)

    assert len(result["summary"]["scope"]["pages_considered"]) <= 3
    assert result["summary"]["scope"]["pages_considered"] == [1, 2, 3]
    assert "summary_truncated_by_max_pages" in result["warnings"]


def test_empty_document_returns_structured_error() -> None:
    repository = FixtureRepository([])

    result = summarize_document(repository, "doc1")

    assert result["status"] == "error"
    assert result["error"]["code"] == "no_evidence_blocks"
    assert result["citations"] == []
    assert result["summary"] is None


def test_no_textual_evidence_returns_unsupported() -> None:
    repository = FixtureRepository(
        [
            {
                "doc_id": "doc1",
                "block_id": "doc1_p001_image",
                "block_type": "image",
                "text": "",
                "image_path": "images/page1.png",
                "page_id": 1,
                "location": {"page": 1, "block_id": "doc1_p001_image"},
            }
        ]
    )

    result = summarize_document(repository, "doc1")

    assert result["status"] == "unsupported"
    assert result["error"]["code"] == "no_textual_evidence_for_summary"
    assert result["citations"] == []


def test_summary_does_not_use_llm_vlm_training() -> None:
    repository = FixtureRepository([_block(1, 1, "DocAgent deterministic summary test document.")])

    result = summarize_document(repository, "doc1")

    assert result["trace"]["used_llm"] is False
    assert result["trace"]["used_vlm"] is False
    assert result["trace"]["used_training"] is False
