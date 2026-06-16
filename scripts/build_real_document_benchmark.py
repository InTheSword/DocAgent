from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.phase3_focused import corpus_hash, qid_hash, validate_benchmark_contract
from docagent.ingestion.hashing import sha256_file
from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.utils.jsonl import read_jsonl, write_jsonl


ANSWER_TYPE_MAP = {
    "text": "extractive",
    "number": "numeric",
    "table_lookup": "extractive",
    "ranking": "extractive",
    "comparison": "extractive",
    "chart": "visual",
}


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def _safe_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def load_blocks(path: Path) -> list[EvidenceBlock]:
    return [EvidenceBlock.from_dict(record) for record in read_jsonl(path)]


def retrieval_blocks(blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
    return [
        block
        for block in blocks
        if block.block_type != "page"
        and not block.metadata.get("is_boilerplate")
        and not block.metadata.get("exclude_from_retrieval")
        and bool(block.retrieval_text)
    ]


def scenario_status(record: dict[str, Any]) -> str:
    return str(record.get("verification_status") or ("scenario_verified_by_repository_review" if record.get("verified") else "draft"))


def verified_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if bool(record.get("verified")) or scenario_status(record) == "scenario_verified_by_repository_review"
    ]


def qa_sample(record: dict[str, Any]) -> dict[str, Any]:
    answer_type = ANSWER_TYPE_MAP.get(str(record.get("answer_type") or "text"), "extractive")
    answers = [str(item) for item in record.get("answers") or [] if str(item).strip()]
    gold_block_ids = [str(item) for item in record.get("gold_block_ids") or [] if str(item).strip()]
    gold_pages = [int(item) for item in record.get("gold_pages") or []]
    return DocAgentSample(
        qid=str(record["qid"]),
        source="real_document_scenario",
        doc_id=str(record["doc_id"]),
        question=str(record["question"]),
        answer=answers[0] if len(answers) == 1 else answers,
        answer_type=answer_type,
        evidence=[],
        verifiable=True,
        split="scenario",
        metadata={
            "gold_block_ids": gold_block_ids,
            "gold_pages": gold_pages,
            "answers": answers,
            "scenario_answer_type": record.get("answer_type"),
            "verification_status": scenario_status(record),
            "evidence_note": record.get("evidence_note"),
            "metrics_eligible": True,
        },
    ).to_dict()


def validate_real_document_records(records: list[dict[str, Any]], blocks_by_id: dict[str, EvidenceBlock]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for record in records:
        qid = str(record.get("qid") or "")
        if not qid:
            errors.append("missing qid")
        if qid in seen:
            errors.append(f"{qid}: duplicate qid")
        seen.add(qid)
        if not record.get("question"):
            errors.append(f"{qid}: missing question")
        if not record.get("answers"):
            errors.append(f"{qid}: missing answers")
        gold_ids = [str(item) for item in record.get("gold_block_ids") or []]
        if not gold_ids:
            errors.append(f"{qid}: missing gold_block_ids")
        for block_id in gold_ids:
            if block_id not in blocks_by_id:
                errors.append(f"{qid}: gold block missing from corpus: {block_id}")
        if scenario_status(record) != "scenario_verified_by_repository_review":
            errors.append(f"{qid}: record is not verified for metrics")
    return errors


def build_contract(
    *,
    document_dir: Path,
    qa_path: Path,
    output_dir: Path,
    benchmark_id: str,
    write_outputs: bool = True,
) -> dict[str, Any]:
    blocks_path = document_dir / "evidence_blocks.jsonl"
    if not blocks_path.is_file():
        raise FileNotFoundError(f"evidence_blocks.jsonl missing: {blocks_path}")
    all_blocks = load_blocks(blocks_path)
    corpus = retrieval_blocks(all_blocks)
    blocks_by_id = {block.block_id: block for block in corpus}
    if len(blocks_by_id) != len(corpus):
        raise RuntimeError("duplicate block_id in retrieval corpus")
    raw_qa = read_jsonl(qa_path)
    verified = verified_records(raw_qa)
    draft_count = len(raw_qa) - len(verified)
    errors = validate_real_document_records(verified, blocks_by_id)
    if errors:
        raise RuntimeError("invalid real-document QA contract: " + "; ".join(errors[:20]))
    qa_records = [qa_sample(record) for record in verified]
    samples = [DocAgentSample.from_dict(record) for record in qa_records]
    contract = validate_benchmark_contract(
        samples,
        input_path=f"{benchmark_id}_qa.jsonl",
        corpus_blocks=corpus,
        corpus_input_path=f"{benchmark_id}_corpus.jsonl",
    )
    if contract.status != "ready":
        raise RuntimeError("invalid retrieval contract: " + "; ".join(contract.errors))

    qa_output = output_dir / f"{benchmark_id}_qa.jsonl"
    corpus_output = output_dir / f"{benchmark_id}_corpus.jsonl"
    document_manifest_output = output_dir / f"{benchmark_id}_document_manifest.json"
    benchmark_manifest_output = output_dir / f"{benchmark_id}_benchmark_manifest.json"
    if write_outputs:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(qa_output, qa_records)
        write_jsonl(corpus_output, [block.to_dict() for block in corpus])

    ingestion_report = document_dir / "ingestion_report.json"
    structure_quality = document_dir / "structure_quality.json"
    source_pdf = document_dir / "source" / "original.pdf"
    document_manifest = {
        "artifact_role": "real_document_manifest",
        "doc_id": corpus[0].doc_id if corpus else None,
        "document_dir": _safe_path(document_dir),
        "source_pdf": _safe_path(source_pdf) if source_pdf.is_file() else None,
        "source_sha256": sha256_file(source_pdf) if source_pdf.is_file() else None,
        "ingestion_report": _safe_path(ingestion_report) if ingestion_report.is_file() else None,
        "structure_quality": _safe_path(structure_quality) if structure_quality.is_file() else None,
        "corpus_block_count": len(corpus),
        "all_block_count": len(all_blocks),
        "page_count": len({block.page_id for block in all_blocks if block.page_id is not None}),
    }
    benchmark_manifest = {
        "artifact_role": "real_document_regression_manifest",
        "benchmark_id": benchmark_id,
        "result_type": "real-document regression/scenario QA, not a formal benchmark",
        "source_dataset": "repository real document scenario",
        "qa_artifact": _safe_path(qa_output),
        "corpus_artifact": _safe_path(corpus_output),
        "document_manifest": _safe_path(document_manifest_output),
        "corpus_source": "full_non_boilerplate_document_evidence_blocks",
        "corpus_is_query_independent": True,
        "one_corpus_signature_per_doc": True,
        "sample_count": len(qa_records),
        "draft_sample_count": draft_count,
        "document_count": len({block.doc_id for block in corpus}),
        "block_count": len(corpus),
        "qid_hash": qid_hash([record["qid"] for record in qa_records]),
        "corpus_hash": corpus_hash(corpus),
        "gold_block_coverage": contract.gold_block_coverage,
        "retrieval_contract": contract.to_dict(),
    }
    if write_outputs:
        document_manifest_output.write_text(json.dumps(document_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        benchmark_manifest_output.write_text(json.dumps(benchmark_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "command": "build_real_document_benchmark",
        "status": "success",
        "artifact_paths": (
            {
                "qa": _safe_path(qa_output),
                "corpus": _safe_path(corpus_output),
                "document_manifest": _safe_path(document_manifest_output),
                "benchmark_manifest": _safe_path(benchmark_manifest_output),
            }
            if write_outputs
            else {}
        ),
        "metrics": {
            "sample_count": len(qa_records),
            "draft_sample_count": draft_count,
            "document_count": benchmark_manifest["document_count"],
            "block_count": len(corpus),
            "qid_hash": benchmark_manifest["qid_hash"],
            "corpus_hash": benchmark_manifest["corpus_hash"],
            "gold_block_coverage": contract.gold_block_coverage,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a query-independent real-document regression contract.")
    parser.add_argument("--document-dir", required=True)
    parser.add_argument("--qa-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--benchmark-id", default="globocan_africa_2022_regression")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = 0
    try:
        output_dir = repo_path(args.output_dir)
        payload = build_contract(
            document_dir=repo_path(args.document_dir),
            qa_path=repo_path(args.qa_path),
            output_dir=output_dir,
            benchmark_id=args.benchmark_id,
            write_outputs=not args.validate_only,
        )
    except Exception as exc:
        exit_code = 1
        payload = {
            "command": "build_real_document_benchmark",
            "status": "failed",
            "exit_code": 1,
            "exception": f"{type(exc).__name__}: {exc}",
            "log_tail": "",
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
