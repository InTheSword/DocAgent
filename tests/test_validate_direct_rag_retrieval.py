from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.validate_direct_rag_retrieval import run_validation


def test_direct_validation_rebuilds_chunks_and_separates_table_routes(tmp_path: Path) -> None:
    content_list = tmp_path / "content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "page_idx": 0, "text": "DocAgent supports direct retrieval."},
                {
                    "type": "table",
                    "page_idx": 0,
                    "table_body": (
                        "<table><tr><td>Method</td><td>Score</td></tr>"
                        "<tr><td>DocAgent</td><td>82</td></tr></table>"
                    ),
                },
            ]
        ),
        encoding="utf-8",
    )
    samples = tmp_path / "samples.jsonl"
    samples.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "qid": "ordinary",
                        "question": "direct retrieval",
                        "query_type": "keyword",
                        "target_modality": "text",
                        "gold_block_ids": ["doc_p001_b0001"],
                    }
                ),
                json.dumps(
                    {
                        "qid": "table_text",
                        "question": "DocAgent score table",
                        "query_type": "keyword",
                        "target_modality": "table",
                        "gold_block_ids": ["doc_p001_b0002"],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    table_samples = tmp_path / "table_samples.jsonl"
    table_samples.write_text(
        json.dumps(
            {
                "qid": "table_structured",
                "question": "What is the DocAgent score?",
                "query_type": "table_structured",
                "target_modality": "table",
                "gold_block_ids": ["doc_p001_b0002"],
                "table_query": {
                    "filters": {"Method": "DocAgent"},
                    "select_columns": ["Score"],
                },
                "expected_structured": {
                    "block_id": "doc_p001_b0002",
                    "selected_rows": [{"Score": "82"}],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    args = argparse.Namespace(
        run_id="fixture",
        doc_id="doc",
        content_list=str(content_list),
        samples=str(samples),
        table_samples=str(table_samples),
        document_dir=str(tmp_path),
        output_dir=str(output_dir),
        top_k=2,
        dense_backend="hash",
        dense_model_path=None,
        reranker_model_path=None,
        device="cpu",
        no_fp16=True,
        dense_batch_size=8,
        dense_max_length=8192,
        reranker_batch_size=4,
        reranker_max_length=4096,
    )

    result = run_validation(args)
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))

    assert result["status"] == "success"
    assert summary["chunk_rebuild"]["contract_error_count"] == 0
    assert summary["chunk_rebuild"]["structured_table_count"] == 1
    assert summary["retrieval"]["query_rewrite_enabled"] is False
    assert summary["retrieval"]["intent_router_enabled"] is False
    assert summary["retrieval"]["buckets"]["ordinary"]["hit_rate_at_k"] == 1.0
    assert summary["retrieval"]["buckets"]["table_text"]["hit_rate_at_k"] == 1.0
    assert summary["retrieval"]["structured_exact_match_rate"] == 1.0
