from __future__ import annotations

from docagent.retrieval.base import RetrievalFilter
from docagent.retrieval.dense_encoder import HashDenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.metadata_filter import infer_metadata_filter
from docagent.schemas import EvidenceBlock, EvidenceLocation


def _block(
    block_id: str,
    text: str,
    *,
    page: int,
    block_type: str = "text",
    content_type: str = "body",
    raw_type: str = "text",
    printed_page: str | None = None,
    heading_role: str | None = None,
    section_path: list[str] | None = None,
) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc",
        block_id=block_id,
        block_type=block_type,
        text=text,
        page_id=page,
        location=EvidenceLocation(page=page, block_id=block_id),
        metadata={
            "content_type": content_type,
            "raw_mineru_type": raw_type,
            "printed_page_number": printed_page,
            "heading_role": heading_role,
            "section_path": section_path or [],
            "reading_order": int(block_id.removeprefix("b")),
        },
    )


def _corpus() -> list[EvidenceBlock]:
    return [
        _block(
            "b1",
            "VideoTree paper",
            page=1,
            content_type="heading",
            heading_role="document_title",
        ),
        _block("b2", "Visual clustering operation", page=3, section_path=["Method", "Visual Tree"]),
        _block("b3", "Efficiency results", page=7, block_type="table", content_type="table", raw_type="table"),
        _block("b4", "Ablation results", page=7, block_type="table", content_type="table", raw_type="table"),
        _block("b5", "Accuracy results", page=7, block_type="table", content_type="table", raw_type="table"),
        _block("b6", "Number of captions", page=7, block_type="image", content_type="chart", raw_type="chart"),
        _block("b7", "Appendix note", page=9, printed_page="iv"),
    ]


def test_infer_metadata_filter_avoids_generic_visual_text() -> None:
    assert infer_metadata_filter("visual clustering operation").is_empty
    assert infer_metadata_filter("Retrieve the paper title on page 1.").to_dict() == {
        "page_ids": [1],
        "content_types": ["heading"],
        "heading_roles": ["document_title"],
    }
    assert infer_metadata_filter("Find the chart block on page 7.").to_dict() == {
        "page_ids": [7],
        "content_types": ["chart"],
        "raw_mineru_types": ["chart"],
    }


def test_bm25_metadata_filters_return_navigation_sets() -> None:
    retriever = IndexedDocumentRetriever(_corpus(), mode="bm25")

    title = retriever.retrieve(doc_id="doc", question="Retrieve the paper title on page 1.", top_k=5)
    tables = retriever.retrieve(doc_id="doc", question="Retrieve all table chunks on page 7.", top_k=5)
    chart = retriever.retrieve(doc_id="doc", question="Find the chart block on page 7.", top_k=5)
    visual = retriever.retrieve(doc_id="doc", question="Find the visual blocks on page 7.", top_k=5)

    assert [item.block.block_id for item in title.candidates] == ["b1"]
    assert [item.block.block_id for item in tables.candidates] == ["b3", "b4", "b5"]
    assert [item.block.block_id for item in chart.candidates] == ["b6"]
    assert [item.block.block_id for item in visual.candidates] == ["b3", "b4", "b5", "b6"]
    assert visual.metadata["metadata_filter"]["page_ids"] == [7]
    assert visual.metadata["pre_filter_block_count"] == 7
    assert visual.metadata["post_filter_block_count"] == 4


def test_dense_search_is_restricted_to_metadata_candidate_subset() -> None:
    blocks = _corpus()
    encoder = HashDenseEncoder()
    dense_index = DenseIndex.build(
        blocks=blocks,
        embeddings=encoder.encode_documents([block.retrieval_text for block in blocks]),
        model_id=encoder.model_id,
    )
    retriever = IndexedDocumentRetriever(
        blocks,
        mode="dense",
        dense_encoder=encoder,
        dense_index=dense_index,
    )

    result = retriever.retrieve(
        doc_id="doc",
        question="Retrieve all table chunks on page 7.",
        top_k=5,
    )

    assert {item.block.block_id for item in result.candidates} == {"b3", "b4", "b5"}
    assert result.metadata["post_filter_block_count"] == 3


def test_printed_page_filter_is_distinct_from_document_page() -> None:
    retriever = IndexedDocumentRetriever(_corpus(), mode="bm25")

    result = retriever.retrieve(
        doc_id="doc",
        question="Find the text on printed page iv.",
        top_k=5,
    )

    assert [item.block.block_id for item in result.candidates] == ["b7"]


def test_structured_filter_supports_page_ranges_sections_and_tags() -> None:
    inferred = infer_metadata_filter("Retrieve table blocks on pages 6-7.")
    assert inferred.page_ids == (6, 7)
    assert inferred.content_types == ("table",)

    block = _corpus()[1]
    block.metadata["feature_tags"] = ["content_type:body", "reviewed"]
    assert RetrievalFilter(
        page_ids=(3,),
        section_queries=("visual tree",),
        feature_tags=("reviewed",),
    ).matches(block)
    assert not RetrievalFilter(section_queries=("results",)).matches(block)


def test_hybrid_retrieval_uses_metadata_only_as_a_candidate_prefilter() -> None:
    blocks = _corpus()
    encoder = HashDenseEncoder()
    dense_index = DenseIndex.build(
        blocks=blocks,
        embeddings=encoder.encode_documents([block.retrieval_text for block in blocks]),
        model_id=encoder.model_id,
    )
    retriever = IndexedDocumentRetriever(
        blocks,
        mode="hybrid",
        dense_encoder=encoder,
        dense_index=dense_index,
    )

    result = retriever.retrieve(
        doc_id="doc",
        question="Retrieve all table chunks on page 7.",
        top_k=5,
    )

    assert {item.block.block_id for item in result.candidates} == {"b3", "b4", "b5"}
    assert all("metadata" not in item.sources for item in result.candidates)
    assert result.metadata["retrieval_routes"] == ["bm25", "dense"]
    assert result.metadata["metadata_filter_source"] == "inferred"


def test_explicit_block_filter_is_applied_before_all_candidate_routes() -> None:
    blocks = _corpus()
    encoder = HashDenseEncoder()
    dense_index = DenseIndex.build(
        blocks=blocks,
        embeddings=encoder.encode_documents([block.retrieval_text for block in blocks]),
        model_id=encoder.model_id,
    )
    retriever = IndexedDocumentRetriever(
        blocks,
        mode="hybrid",
        dense_encoder=encoder,
        dense_index=dense_index,
    )

    result = retriever.retrieve(
        doc_id="doc",
        question="results",
        top_k=5,
        filters=RetrievalFilter(block_ids=("b4",)),
    )

    assert [item.block.block_id for item in result.candidates] == ["b4"]
    assert result.metadata["pre_filter_block_count"] == 7
    assert result.metadata["post_filter_block_count"] == 1


def test_dense_route_encodes_the_same_rewritten_query_used_for_retrieval() -> None:
    blocks = _corpus()

    class CapturingEncoder(HashDenseEncoder):
        def __init__(self) -> None:
            super().__init__()
            self.queries: list[str] = []

        def encode_queries(self, texts: list[str]):
            self.queries = list(texts)
            return super().encode_queries(texts)

    encoder = CapturingEncoder()
    dense_index = DenseIndex.build(
        blocks=blocks,
        embeddings=encoder.encode_documents([block.retrieval_text for block in blocks]),
        model_id=encoder.model_id,
    )
    retriever = IndexedDocumentRetriever(
        blocks,
        mode="dense",
        dense_encoder=encoder,
        dense_index=dense_index,
    )

    retriever.retrieve(doc_id="doc", question="revenue 2023", top_k=2)

    assert encoder.queries == ["revenue 2023 2023 revenue"]


def test_direct_retrieval_can_disable_query_rewrite() -> None:
    blocks = _corpus()

    class CapturingEncoder(HashDenseEncoder):
        def __init__(self) -> None:
            super().__init__()
            self.queries: list[str] = []

        def encode_queries(self, texts: list[str]):
            self.queries = list(texts)
            return super().encode_queries(texts)

    encoder = CapturingEncoder()
    dense_index = DenseIndex.build(
        blocks=blocks,
        embeddings=encoder.encode_documents([block.retrieval_text for block in blocks]),
        model_id=encoder.model_id,
    )
    retriever = IndexedDocumentRetriever(
        blocks,
        mode="hybrid",
        dense_encoder=encoder,
        dense_index=dense_index,
    )

    result = retriever.retrieve(
        doc_id="doc",
        question="revenue 2023",
        top_k=2,
        enable_query_rewrite=False,
    )

    assert encoder.queries == ["revenue 2023"]
    assert result.rewritten_query == "revenue 2023"
    assert result.metadata["query_rewrite_enabled"] is False
