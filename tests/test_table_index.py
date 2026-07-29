from __future__ import annotations

from docagent.retrieval.dense_encoder import HashDenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.table_index import TableRelationalIndex, TableStructuredQuery
from docagent.schemas import Chunk, EvidenceLocation


def _chunk(
    block_id: str,
    text: str,
    *,
    block_type: str = "text",
    headers: list[str] | None = None,
    rows: list[list[str]] | None = None,
) -> Chunk:
    return Chunk(
        doc_id="doc",
        block_id=block_id,
        block_type=block_type,
        text=text,
        page_id=1,
        location=EvidenceLocation(page=1, block_id=block_id),
        metadata={
            "content_type": block_type if block_type == "table" else "body",
            "reading_order": int(block_id.removeprefix("b")),
            "table_headers": headers or [],
            "table_rows": rows or [],
        },
    )


def _corpus() -> list[Chunk]:
    return [
        _chunk("b1", "The annual report describes revenue growth."),
        _chunk(
            "b2",
            "| Year | Region | Revenue |\n| --- | --- | --- |\n| 2023 | East | 120 |\n| 2023 | West | 80 |",
            block_type="table",
            headers=["Year", "Region", "Revenue"],
            rows=[["2023", "East", "120"], ["2023", "West", "80"]],
        ),
        _chunk(
            "b3",
            "| Year | Region | Revenue |\n| --- | --- | --- |\n| 2022 | East | 90 |",
            block_type="table",
            headers=["Year", "Region", "Revenue"],
            rows=[["2022", "East", "90"]],
        ),
    ]


def test_table_relational_index_filters_selects_and_aggregates_rows() -> None:
    query = TableStructuredQuery(
        filters={"Year": "2023"},
        select_columns=("Region", "Revenue"),
        aggregation="sum",
        aggregation_column="Revenue",
    )

    hits = TableRelationalIndex(_corpus()).search(query, top_k=5)

    assert [hit.block.block_id for hit in hits] == ["b2"]
    assert hits[0].selected_rows == [
        {"Region": "East", "Revenue": "120"},
        {"Region": "West", "Revenue": "80"},
    ]
    assert hits[0].aggregate == {
        "operation": "sum",
        "column": "Revenue",
        "value": 200.0,
    }


def test_table_intent_merges_text_and_relational_results_after_prefilter() -> None:
    chunks = _corpus()
    encoder = HashDenseEncoder()
    dense_index = DenseIndex.build(
        blocks=chunks,
        embeddings=encoder.encode_documents([chunk.retrieval_text for chunk in chunks]),
        model_id=encoder.model_id,
    )
    retriever = IndexedDocumentRetriever(
        chunks,
        mode="hybrid",
        dense_encoder=encoder,
        dense_index=dense_index,
    )

    result = retriever.retrieve(
        doc_id="doc",
        question="What is the 2023 revenue by region?",
        top_k=3,
        query_intent="table",
        table_query={
            "filters": {"Year": "2023"},
            "select_columns": ["Region", "Revenue"],
        },
    )

    assert result.metadata["post_filter_block_count"] == 2
    assert result.metadata["metadata_filter"] == {
        "block_types": ["table"],
        "content_types": ["table"],
    }
    assert result.metadata["retrieval_routes"] == ["bm25", "dense", "table_structured"]
    assert result.metadata["table_structured_results"][0]["block_id"] == "b2"
    b2 = next(candidate for candidate in result.candidates if candidate.block.block_id == "b2")
    assert "table_structured" in b2.sources
    assert b2.table_score == 2.0


def test_non_table_intent_keeps_the_normal_hybrid_routes() -> None:
    chunks = _corpus()
    encoder = HashDenseEncoder()
    dense_index = DenseIndex.build(
        blocks=chunks,
        embeddings=encoder.encode_documents([chunk.retrieval_text for chunk in chunks]),
        model_id=encoder.model_id,
    )
    retriever = IndexedDocumentRetriever(
        chunks,
        mode="hybrid",
        dense_encoder=encoder,
        dense_index=dense_index,
    )

    result = retriever.retrieve(
        doc_id="doc",
        question="Describe the report.",
        top_k=2,
    )

    assert result.metadata["retrieval_routes"] == ["bm25", "dense"]
    assert "table_structured_results" not in result.metadata
