from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata, util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def _status(ok: bool, missing_status: str = "missing") -> str:
    return "ready" if ok else missing_status


def _git_info() -> dict[str, Any]:
    def run_git(*args: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception:
            return None
        return completed.stdout.strip()

    return {
        "commit": run_git("rev-parse", "HEAD"),
        "branch": run_git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(run_git("status", "--porcelain")),
    }


def _runtime_info() -> dict[str, Any]:
    torch = {
        "installed": util.find_spec("torch") is not None,
        "version": _package_version("torch"),
        "cuda_available": None,
        "cuda_device_count": None,
        "cuda_version": None,
        "mode": "torch_missing",
        "import_error": None,
    }
    if torch["installed"]:
        try:
            import torch as torch_module

            cuda_available = bool(torch_module.cuda.is_available())
            torch.update(
                {
                    "version": getattr(torch_module, "__version__", torch["version"]),
                    "cuda_available": cuda_available,
                    "cuda_device_count": int(torch_module.cuda.device_count()) if cuda_available else 0,
                    "cuda_version": getattr(torch_module.version, "cuda", None),
                    "mode": "gpu" if cuda_available else "no_card_or_cpu",
                }
            )
        except Exception as exc:
            torch["mode"] = "torch_import_failed"
            torch["import_error"] = f"{type(exc).__name__}: {exc}"
    return {
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "torch": torch,
    }


def _package_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _package_info(module: str, *, distribution: str | None = None) -> dict[str, Any]:
    distribution = distribution or module
    present = util.find_spec(module) is not None
    return {
        "module": module,
        "distribution": distribution,
        "present": present,
        "version": _package_version(distribution),
        "status": _status(present),
    }


def _model_path_info(name: str, path: str | Path) -> dict[str, Any]:
    model_path = _repo_path(path)
    config_file = model_path / "config.json"
    tokenizer_candidates = [
        model_path / "tokenizer.json",
        model_path / "tokenizer.model",
        model_path / "tokenizer_config.json",
    ]
    files = {
        "config_json": config_file.exists(),
        "tokenizer_any": any(candidate.exists() for candidate in tokenizer_candidates),
    }
    exists = model_path.exists()
    ready = exists and all(files.values())
    return {
        "name": name,
        "path": str(model_path),
        "exists": exists,
        "files": files,
        "status": _status(ready, "incomplete" if exists else "missing"),
    }


def _inspect_benchmark(paths: list[str]) -> dict[str, Any]:
    artifacts = []
    for raw_path in paths:
        path = _repo_path(raw_path)
        info: dict[str, Any] = {
            "path": str(path),
            "exists": path.exists(),
            "status": "missing",
            "sample_records_checked": 0,
            "has_evidence_blocks": False,
        }
        if path.exists():
            checked = 0
            has_evidence = False
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if checked >= 5:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        checked += 1
                        record = json.loads(line)
                        evidence = record.get("evidence")
                        if isinstance(evidence, list) and evidence:
                            has_evidence = all(
                                isinstance(item, dict) and item.get("block_id") and item.get("doc_id")
                                for item in evidence[:3]
                            )
            except Exception as exc:
                info["status"] = "unreadable"
                info["error"] = f"{type(exc).__name__}: {exc}"
            else:
                info["sample_records_checked"] = checked
                info["has_evidence_blocks"] = has_evidence
                info["status"] = _status(has_evidence, "incomplete")
        artifacts.append(info)
    return {
        "status": _status(any(item["status"] == "ready" for item in artifacts), "missing"),
        "artifacts": artifacts,
    }


def _inspect_dense_indexes(root: str | Path, sqlite_path: str | Path) -> dict[str, Any]:
    root_path = _repo_path(root)
    filesystem = []
    if root_path.exists():
        for metadata_path in sorted(root_path.rglob("index_metadata*.json"))[:10]:
            item: dict[str, Any] = {"metadata_path": str(metadata_path), "status": "unreadable"}
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
            else:
                embeddings_path = Path(str(payload.get("embeddings_path") or ""))
                if not embeddings_path.is_absolute():
                    embeddings_path = metadata_path.parent / embeddings_path
                faiss_path = payload.get("faiss_path")
                item.update(
                    {
                        "model_id": payload.get("model_id"),
                        "backend": payload.get("backend"),
                        "embeddings_exists": embeddings_path.exists(),
                        "faiss_path": faiss_path,
                        "faiss_exists": Path(faiss_path).exists() if faiss_path else None,
                        "status": _status(embeddings_path.exists(), "incomplete"),
                    }
                )
            filesystem.append(item)

    sqlite_info = _inspect_sqlite_indexes(sqlite_path)
    ready = any(item.get("status") == "ready" for item in filesystem) or sqlite_info.get("count", 0) > 0
    return {
        "status": _status(ready, "optional_missing"),
        "root": str(root_path),
        "filesystem": filesystem,
        "sqlite": sqlite_info,
    }


def _inspect_sqlite_indexes(sqlite_path: str | Path) -> dict[str, Any]:
    path = _repo_path(sqlite_path)
    info: dict[str, Any] = {"path": str(path), "exists": path.exists(), "count": 0, "status": "missing"}
    if not path.exists():
        return info
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM document_indexes WHERE index_type = 'dense'"
            ).fetchone()
    except Exception as exc:
        info["status"] = "unreadable"
        info["error"] = f"{type(exc).__name__}: {exc}"
    else:
        info["count"] = int(row[0] if row else 0)
        info["status"] = _status(info["count"] > 0, "empty")
    return info


def _inspect_mineru_outputs(root: str | Path) -> dict[str, Any]:
    root_path = _repo_path(root)
    outputs = []
    if root_path.exists():
        for path in sorted(root_path.rglob("*content_list*.json"))[:10]:
            outputs.append(str(path))
    return {
        "status": _status(bool(outputs), "optional_missing"),
        "root": str(root_path),
        "content_list_paths": outputs,
        "note": "presence check only; does not verify real MinerU execution",
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    packages = {
        "FlagEmbedding": _package_info("FlagEmbedding", distribution="FlagEmbedding"),
        "faiss": _package_info("faiss", distribution="faiss-cpu"),
        "reranker_required": [
            _package_info("FlagEmbedding", distribution="FlagEmbedding"),
        ],
    }
    models = {
        "qwen3": _model_path_info("qwen3", args.qwen_model_path),
        "bge_m3": _model_path_info("bge_m3", args.bge_model_path),
        "bge_reranker_v2_m3": _model_path_info("bge_reranker_v2_m3", args.reranker_model_path),
    }
    artifacts = {
        "benchmark_evidence": _inspect_benchmark(args.benchmark_artifact),
        "dense_index": _inspect_dense_indexes(args.dense_index_root, args.sqlite_path),
        "real_mineru_output": _inspect_mineru_outputs(args.mineru_output_root),
    }
    missing_required = []
    for name, info in packages.items():
        if isinstance(info, dict) and info.get("status") != "ready":
            missing_required.append(f"package:{name}")
    for name, info in models.items():
        if info.get("status") != "ready":
            missing_required.append(f"model:{name}")
    if artifacts["benchmark_evidence"]["status"] != "ready":
        missing_required.append("artifact:benchmark_evidence")
    optional_missing = [
        name for name in ("dense_index", "real_mineru_output") if artifacts[name]["status"] != "ready"
    ]
    return {
        "command": "phase2_preflight",
        "status": "success",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": _git_info(),
        "runtime": _runtime_info(),
        "packages": packages,
        "models": models,
        "artifacts": artifacts,
        "summary": {
            "ready_for_real_retrieval_smoke": not missing_required,
            "missing_required": missing_required,
            "optional_missing": optional_missing,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qwen-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--bge-model-path", default="/root/autodl-tmp/models/bge-m3")
    parser.add_argument("--reranker-model-path", default="/root/autodl-tmp/models/bge-reranker-v2-m3")
    parser.add_argument(
        "--benchmark-artifact",
        action="append",
        default=[
            "data/benchmark/mp_docvqa_dev_sft_retrieved_clean.jsonl",
            "data/benchmark/smoke_eval.jsonl",
        ],
    )
    parser.add_argument("--dense-index-root", default="data/documents")
    parser.add_argument("--mineru-output-root", default="data/documents")
    parser.add_argument("--sqlite-path", default="outputs/docagent.db")
    parser.add_argument("--output", default="outputs/preflight/phase2.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(args)
    output = _repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
