from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.router.llm_client import (
    OpenAICompatibleRouterClient,
    load_router_llm_config,
    parse_json_object,
)
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.build_m1_chunk_qrels import _load_corpus, freeze_qrels

SYSTEM_PROMPT = (
    "You independently review retrieval qrels. Compare the verbatim source evidence with the proposed "
    "complete Chunk sets. Return only one JSON object with exactly: decision, "
    "selected_candidate_indexes, rationale. decision must be accept_candidate or exclude. "
    "Indexes are zero-based and must identify complete candidate sets; never select part of a set. "
    "Accept only candidates that preserve all material facts in the source evidence. Exclude when no "
    "candidate is sufficient. rationale must be one brief sentence. Do not answer the question, output "
    "confidence, Markdown, citations, chain-of-thought, or extra fields."
)
OUTPUT_FIELDS = {"decision", "selected_candidate_indexes", "rationale"}
TRANSIENT_API_MARKERS = (
    "429",
    "too many requests",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "http error 502",
    "http error 503",
    "http error 504",
)


class QrelsReviewError(ValueError):
    pass


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _review_payload(item: Mapping[str, Any], correction: str = "") -> dict[str, Any]:
    payload = {
        "sample_id": item["sample_id"],
        "group_id": item["group_id"],
        "question": item["question"],
        "source_evidence": item["source_evidence"],
        "candidate_class": item["candidate_class"],
        "candidates": [
            {
                "candidate_index": index,
                "chunk_ids": candidate["chunk_ids"],
                "pages": candidate["pages"],
                "block_types": candidate["block_types"],
                "match_method": candidate["match_method"],
                "match_score": candidate["match_score"],
                "preview": candidate["preview"],
            }
            for index, candidate in enumerate(item["candidates"])
        ],
    }
    if correction:
        payload["correction"] = correction
    return payload


def _validate_review_output(payload: dict[str, Any] | None, candidate_count: int) -> dict[str, Any]:
    if payload is None or set(payload) != OUTPUT_FIELDS:
        raise QrelsReviewError("output must contain exactly decision, selected_candidate_indexes, rationale")
    decision = payload.get("decision")
    if decision not in {"accept_candidate", "exclude"}:
        raise QrelsReviewError("decision must be accept_candidate or exclude")
    indexes = payload.get("selected_candidate_indexes")
    if not isinstance(indexes, list) or any(isinstance(index, bool) or not isinstance(index, int) for index in indexes):
        raise QrelsReviewError("selected_candidate_indexes must be an integer array")
    if len(indexes) != len(set(indexes)) or any(index < 0 or index >= candidate_count for index in indexes):
        raise QrelsReviewError("selected_candidate_indexes contains duplicates or an invalid index")
    if decision == "accept_candidate" and not indexes:
        raise QrelsReviewError("accept_candidate requires at least one complete candidate")
    if decision == "exclude" and indexes:
        raise QrelsReviewError("exclude cannot select candidates")
    rationale = str(payload.get("rationale") or "").strip()
    if not rationale or len(rationale) > 500:
        raise QrelsReviewError("rationale must contain 1 to 500 characters")
    return {"decision": decision, "selected_candidate_indexes": indexes, "rationale": rationale}


def review_queue_item(
    item: Mapping[str, Any],
    *,
    llm_client: Any,
) -> tuple[dict[str, Any], bool]:
    error = ""
    for attempt in range(2):
        request = {
            "system_prompt": SYSTEM_PROMPT,
            "user_payload": _review_payload(item, correction=error),
        }
        for api_attempt, delay in enumerate((0, 3, 10, 20)):
            if delay:
                time.sleep(delay)
            try:
                raw = llm_client.complete(**request)
                break
            except Exception as exc:
                transient = any(marker in str(exc).lower() for marker in TRANSIENT_API_MARKERS)
                if not transient or api_attempt == 3:
                    raise
        try:
            return _validate_review_output(parse_json_object(raw), len(item["candidates"])), attempt == 1
        except QrelsReviewError as exc:
            error = f"Your previous output was invalid: {exc}. Return a corrected object."
    raise QrelsReviewError(error)


def _decision_from_review(
    template: Mapping[str, Any],
    item: Mapping[str, Any],
    review: Mapping[str, Any],
    *,
    reviewer: str,
) -> dict[str, Any]:
    result = dict(template)
    selected = [item["candidates"][index] for index in review["selected_candidate_indexes"]]
    selected_sets = [list(candidate["chunk_ids"]) for candidate in selected]
    selected_hashes: dict[str, str] = {}
    for candidate in selected:
        selected_hashes.update(candidate["chunk_content_hashes"])
    result.update(
        {
            "decision": review["decision"],
            "selected_chunk_sets": selected_sets,
            "selected_chunk_hashes": selected_hashes,
            "reviewer": reviewer,
            "reviewer_type": "independent_ai",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "rationale": review["rationale"],
        }
    )
    return result


def _manifest(run_id: str, output_dir: Path, files: list[Path]) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "files": [
            {"path": str(path), "size": path.stat().st_size, "sha256": _sha256_file(path)}
            for path in files
            if path.is_file()
        ],
    }


def run(args: argparse.Namespace, *, llm_client: Any | None = None, model_name: str = "") -> dict[str, Any]:
    candidate_dir = _repo_path(args.candidate_dir)
    output_dir = _repo_path(args.output_dir)
    sync_dir = _repo_path(args.sync_dir) if args.sync_dir else None
    candidates = list(read_jsonl(candidate_dir / "chunk_qrels_candidates.jsonl"))
    queue = list(read_jsonl(candidate_dir / "qrels_review_queue.jsonl"))
    templates = list(read_jsonl(candidate_dir / "review_decisions.template.jsonl"))
    human_decisions = list(read_jsonl(_repo_path(args.human_decisions)))
    _manifest_data, _documents, chunks_by_doc = _load_corpus(_repo_path(args.corpus_manifest))

    template_by_key = {(row["sample_id"], row["group_id"]): row for row in templates}
    human_by_key = {(row["sample_id"], row["group_id"]): row for row in human_decisions}
    if len(human_by_key) != len(human_decisions):
        raise ValueError("human decisions contain duplicate sample/group keys")
    remaining = [row for row in queue if (row["sample_id"], row["group_id"]) not in human_by_key]
    if any(not row["candidates"] for row in remaining):
        raise ValueError("an unreviewed evidence group has no candidates")

    if llm_client is None:
        config, warnings = load_router_llm_config(env_file=_repo_path(args.env_file), env={})
        if config is None:
            raise ValueError(f"qrels reviewer LLM is not configured: {warnings}")
        llm_client = OpenAICompatibleRouterClient(config)
        model_name = config.model
    reviewer = f"{model_name or 'configured_llm'}:m1_qrels_reviewer_v1"

    output_dir.mkdir(parents=True, exist_ok=True)
    partial_path = output_dir / "ai_review_decisions.partial.jsonl"
    partial_rows = list(read_jsonl(partial_path)) if partial_path.is_file() else []
    reviewed: dict[tuple[str, str], dict[str, Any]] = {
        (row["sample_id"], row["group_id"]): row for row in partial_rows
    }
    if len(reviewed) != len(partial_rows):
        raise ValueError("partial AI decisions contain duplicate sample/group keys")
    expected_ai_keys = {(row["sample_id"], row["group_id"]) for row in remaining}
    if not set(reviewed).issubset(expected_ai_keys):
        raise ValueError("partial AI decisions do not match the current review queue")
    remaining = [row for row in remaining if (row["sample_id"], row["group_id"]) not in reviewed]
    retried_count = 0
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        futures = {executor.submit(review_queue_item, item, llm_client=llm_client): item for item in remaining}
        for future in as_completed(futures):
            item = futures[future]
            key = (item["sample_id"], item["group_id"])
            try:
                review, retried = future.result()
                reviewed[key] = _decision_from_review(
                    template_by_key[key], item, review, reviewer=reviewer
                )
                write_jsonl(partial_path, [reviewed[key] for key in sorted(reviewed)])
                retried_count += int(retried)
            except Exception as exc:
                failures.append({"sample_id": key[0], "group_id": key[1], "error": str(exc)[:500]})

    failure_path = output_dir / "failures.jsonl"
    write_jsonl(failure_path, failures)
    if failures or len(reviewed) != len(expected_ai_keys):
        raise RuntimeError(f"qrels review failed closed: {len(failures)} failures")

    combined_by_key = {**reviewed, **human_by_key}
    decisions = [combined_by_key[(row["sample_id"], row["group_id"])] for row in templates]
    decisions_path = output_dir / "review_decisions.jsonl"
    write_jsonl(decisions_path, decisions)
    decisions_sha256 = _sha256_file(decisions_path)
    frozen = freeze_qrels(
        candidates,
        decisions,
        chunks_by_doc,
        review_decisions_sha256=decisions_sha256,
    )
    frozen_path = output_dir / "frozen_chunk_qrels.jsonl"
    write_jsonl(frozen_path, frozen)

    action_counts = Counter(row["decision"] for row in decisions)
    summary = {
        "status": "success",
        "milestone_status": "frozen",
        "model": model_name,
        "human_reviewed_group_count": len(human_decisions),
        "independent_ai_reviewed_group_count": len(reviewed),
        "evidence_group_count": len(decisions),
        "decision_counts": dict(sorted(action_counts.items())),
        "semantic_retry_count": retried_count,
        "frozen_sample_count": len(frozen),
        "evaluation_eligible_sample_count": sum(bool(row["evaluation_eligible"]) for row in frozen),
        "excluded_sample_count": sum(not bool(row["evaluation_eligible"]) for row in frozen),
        "review_decisions_sha256": decisions_sha256,
        "frozen_qrels_sha256": _sha256_file(frozen_path),
        "gpu_used": False,
        "retrieval_evaluation_run": False,
    }
    summary_path = output_dir / "summary.json"
    result_path = output_dir / "result.json"
    preview_path = output_dir / "preview.json"
    _write_json(summary_path, summary)
    _write_json(preview_path, frozen[:5])
    result = {
        "command": "review_m1_chunk_qrels",
        "status": "success",
        "artifact_paths": [str(decisions_path), str(frozen_path), str(summary_path)],
        "metrics": summary,
    }
    _write_json(result_path, result)
    manifest_path = output_dir / "manifest.json"
    files = [decisions_path, frozen_path, summary_path, result_path, preview_path, failure_path, partial_path]
    _write_json(manifest_path, _manifest(args.run_id, output_dir, files))

    if sync_dir is not None:
        sync_dir.mkdir(parents=True, exist_ok=True)
        for source in (summary_path, result_path, preview_path, failure_path):
            shutil.copy2(source, sync_dir / source.name)
        (sync_dir / "summary.md").write_text(
            "# M1 frozen Chunk qrels\n\n"
            f"- status: `frozen`\n- groups: {len(decisions)}\n"
            f"- human / independent AI: {len(human_decisions)} / {len(reviewed)}\n"
            f"- decisions: `{dict(sorted(action_counts.items()))}`\n"
            f"- eligible / excluded samples: {summary['evaluation_eligible_sample_count']} / "
            f"{summary['excluded_sample_count']}\n"
            "- GPU/retrieval evaluation: not used\n",
            encoding="utf-8",
        )
        sync_files = [path for path in sync_dir.iterdir() if path.is_file() and path.name != "manifest.json"]
        _write_json(sync_dir / "manifest.json", _manifest(args.run_id, sync_dir, sync_files))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independently review and freeze M1 Chunk qrels")
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--corpus-manifest", required=True)
    parser.add_argument("--human-decisions", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sync-dir", default="")
    parser.add_argument("--run-id", default="m1_frozen_chunk_qrels")
    parser.add_argument("--max-workers", type=int, default=6)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
