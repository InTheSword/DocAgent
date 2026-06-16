from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_path(path: str | Path) -> str:
    value = Path(path)
    try:
        return value.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return value.name


def git_text(args: list[str]) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def log_tail(text: str, limit: int = 60) -> str:
    return "\n".join(text.splitlines()[-limit:])


class AcceptanceRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.output_root = repo_path(args.output_root)
        self.logs = repo_path(args.log_dir)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.artifacts: dict[str, Any] = {}
        self.warnings: list[str] = []

    def run_command(self, name: str, command: list[str], *, allow_failure: bool = False) -> dict[str, Any]:
        proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log_path = self.logs / f"{name}.log"
        log_path.write_text(proc.stdout, encoding="utf-8")
        result = {
            "status": "success" if proc.returncode == 0 else "failed",
            "exit_code": proc.returncode,
            "log": safe_path(log_path),
        }
        if proc.returncode != 0:
            result["log_tail"] = log_tail(proc.stdout)
            if not allow_failure:
                raise RuntimeError(f"{name} failed; see {safe_path(log_path)}")
        return result

    def preflight(self) -> dict[str, Any]:
        branch = git_text(["git", "branch", "--show-current"])
        commit = git_text(["git", "rev-parse", "HEAD"])
        tracked_dirty = bool(git_text(["git", "status", "--porcelain", "--untracked-files=no"]))
        if tracked_dirty:
            raise RuntimeError("tracked git files are dirty")
        cli_results = {}
        for script in (
            "scripts/run_phase3_focused_eval.py",
            "scripts/build_real_document_benchmark.py",
            "scripts/run_phase3_server_acceptance.py",
            "scripts/verify_phase2b_real_e2e.py",
        ):
            cli_results[script] = self.run_command(
                f"help_{Path(script).stem}",
                [sys.executable, script, "--help"],
            )
        cuda = self._cuda_summary()
        paths = self._path_summary()
        globocan = self.build_globocan_contract()
        cdc = self.cdc_status(process=False)
        return {
            "status": "success",
            "branch": branch,
            "commit": commit,
            "tracked_git_clean": True,
            "cuda": cuda,
            "paths": paths,
            "cli_startup": cli_results,
            "globocan_contract": globocan,
            "cdc": cdc,
        }

    def _cuda_summary(self) -> dict[str, Any]:
        code = (
            "import json\n"
            "try:\n"
            " import torch\n"
            " print(json.dumps({'torch': getattr(torch, '__version__', None), 'cuda_available': torch.cuda.is_available(), 'device_count': torch.cuda.device_count()}))\n"
            "except Exception as exc:\n"
            " print(json.dumps({'error': type(exc).__name__ + ': ' + str(exc)}))\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        try:
            return json.loads(proc.stdout)
        except Exception:
            return {"error": log_tail(proc.stdout + proc.stderr, 20)}

    def _path_summary(self) -> dict[str, Any]:
        paths = {
            "bge_model": repo_path(self.args.bge_model_path),
            "reranker_model": repo_path(self.args.reranker_model_path),
            "qwen_base": repo_path(self.args.base_model_path),
            "sft_adapter": repo_path(self.args.sft_adapter_path),
            "grpo_adapter": repo_path(self.args.grpo_adapter_path),
            "mpdocvqa_reader": repo_path(self.args.mpdocvqa_reader_input),
            "globocan_document_dir": repo_path(self.args.globocan_document_dir),
            "globocan_qa": repo_path(self.args.globocan_qa_path),
            "cdc_pdf": repo_path(self.args.cdc_pdf),
        }
        return {name: {"path": safe_path(path), "exists": path.exists()} for name, path in paths.items()}

    def build_globocan_contract(self) -> dict[str, Any]:
        output = self.output_root / "contracts" / "globocan"
        result = self.run_command(
            "build_globocan_contract",
            [
                sys.executable,
                "scripts/build_real_document_benchmark.py",
                "--document-dir",
                str(repo_path(self.args.globocan_document_dir)),
                "--qa-path",
                str(repo_path(self.args.globocan_qa_path)),
                "--output-dir",
                str(output),
                "--benchmark-id",
                "globocan_africa_2022_regression",
            ],
        )
        manifest = output / "globocan_africa_2022_regression_benchmark_manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.artifacts["globocan_contract"] = safe_path(manifest)
        return {
            "status": "ready",
            "evaluation_scope": payload["evaluation_scope"],
            "formal_benchmark": payload["formal_benchmark"],
            "primary_benchmark": payload["primary_benchmark"],
            "source_qa_role": payload["source_qa_role"],
            "qa": payload["qa_artifact"],
            "corpus": payload["corpus_artifact"],
            "manifest": safe_path(manifest),
            "sample_count": payload["sample_count"],
            "verified_qa_count": payload["verified_qa_count"],
            "block_count": payload["block_count"],
            "corpus_is_query_independent": payload["corpus_is_query_independent"],
            "gold_block_coverage": payload["gold_block_coverage"],
            "result": result,
        }

    def cdc_status(self, *, process: bool) -> dict[str, Any]:
        cdc_root = repo_path(self.args.cdc_document_root)
        parsed = list(cdc_root.glob("docagent_documents/*/evidence_blocks.jsonl"))
        if parsed:
            return {
                "status": "ready",
                "document_root": safe_path(cdc_root),
                "evidence_blocks": safe_path(parsed[0]),
            }
        if not process:
            return {"status": "blocked_by_missing_mineru_output", "document_root": safe_path(cdc_root)}
        if not os.getenv("MINERU_TOKEN"):
            return {"status": "blocked_by_missing_mineru_token", "document_root": safe_path(cdc_root)}
        cdc_root.mkdir(parents=True, exist_ok=True)
        result = self.run_command(
            "cdc_mineru_api_ingest",
            [
                sys.executable,
                "scripts/ingest_document.py",
                "--input",
                str(repo_path(self.args.cdc_pdf)),
                "--parser",
                "mineru_api",
                "--live-api",
                "--document-root",
                str(cdc_root / "docagent_documents"),
                "--sqlite-path",
                str(cdc_root / "docagent.sqlite"),
                "--force-parse",
            ],
            allow_failure=True,
        )
        parsed = list(cdc_root.glob("docagent_documents/*/evidence_blocks.jsonl"))
        if result["status"] == "success" and parsed:
            return {"status": "ready", "evidence_blocks": safe_path(parsed[0]), "result": result}
        self.warnings.append("CDC MinerU processing did not complete")
        return {"status": "blocked_by_missing_mineru_output", "result": result}

    def real_document_regression(self) -> dict[str, Any]:
        contract = self.build_globocan_contract()
        run_id = "globocan-real-document-retrieval"
        result = self.run_command(
            "globocan_real_document_retrieval",
            [
                sys.executable,
                "scripts/run_phase3_focused_eval.py",
                "--benchmark-manifest",
                contract["manifest"],
                "--qa-input",
                contract["qa"],
                "--benchmark-input",
                contract["qa"],
                "--corpus-input",
                contract["corpus"],
                "--output-root",
                str(self.output_root / "focused_eval"),
                "--run-id",
                run_id,
                "--force",
                "--retrieval-limit",
                "8",
                "--answer-limit",
                "8",
                "--top-k",
                str(self.args.top_k),
                "--dense-model-path",
                self.args.bge_model_path,
                "--reranker-model-path",
                self.args.reranker_model_path,
                "--dense-device",
                self.args.retrieval_device,
                "--reranker-device",
                self.args.retrieval_device,
            ],
        )
        summary_path = self.output_root / "focused_eval" / run_id / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return {
            "status": "success",
            "evaluation_scope": summary["evaluation_scope"],
            "formal_benchmark": summary["formal_benchmark"],
            "summary": safe_path(summary_path),
            "retrieval": summary["retrieval"]["comparison"],
            "answer_policy": summary["answer_policy"]["comparison"],
            "result": result,
        }

    def answer_policy_eval(self) -> dict[str, Any]:
        reader = repo_path(self.args.mpdocvqa_reader_input)
        if not reader.is_file():
            return {"status": "blocked", "reason": "MP-DocVQA reader artifact missing", "path": safe_path(reader)}
        run_id = "mpdocvqa-answer-policy"
        result = self.run_command(
            "mpdocvqa_answer_policy_eval",
            [
                sys.executable,
                "scripts/run_phase3_focused_eval.py",
                "--benchmark-input",
                str(reader),
                "--answer-only",
                "--output-root",
                str(self.output_root / "focused_eval"),
                "--run-id",
                run_id,
                "--force",
                "--answer-limit",
                str(self.args.answer_limit),
                "--top-k",
                str(self.args.top_k),
                "--base-model-path",
                self.args.base_model_path,
                "--sft-adapter-path",
                self.args.sft_adapter_path,
                "--grpo-adapter-path",
                self.args.grpo_adapter_path,
                "--qwen-device",
                self.args.qwen_device,
            ],
        )
        summary_path = self.output_root / "focused_eval" / run_id / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return {
            "status": "success",
            "summary": safe_path(summary_path),
            "answer_policy": summary["answer_policy"]["comparison"],
            "result": result,
        }

    def focused_eval(self) -> dict[str, Any]:
        qa = repo_path(self.args.mpdocvqa_retrieval_qa)
        corpus = repo_path(self.args.mpdocvqa_retrieval_corpus)
        if not qa.is_file() or not corpus.is_file():
            return {
                "status": "blocked",
                "reason": "MP-DocVQA query-independent retrieval corpus is missing",
                "qa": safe_path(qa),
                "corpus": safe_path(corpus),
            }
        run_id = "mpdocvqa-focused-eval"
        result = self.run_command(
            "mpdocvqa_focused_eval",
            [
                sys.executable,
                "scripts/run_phase3_focused_eval.py",
                "--qa-input",
                str(qa),
                "--benchmark-input",
                str(qa),
                "--corpus-input",
                str(corpus),
                "--output-root",
                str(self.output_root / "focused_eval"),
                "--run-id",
                run_id,
                "--force",
                "--retrieval-limit",
                str(self.args.retrieval_limit),
                "--answer-limit",
                str(self.args.answer_limit),
                "--top-k",
                str(self.args.top_k),
                "--dense-model-path",
                self.args.bge_model_path,
                "--reranker-model-path",
                self.args.reranker_model_path,
                "--base-model-path",
                self.args.base_model_path,
                "--sft-adapter-path",
                self.args.sft_adapter_path,
                "--grpo-adapter-path",
                self.args.grpo_adapter_path,
                "--dense-device",
                self.args.retrieval_device,
                "--reranker-device",
                self.args.retrieval_device,
                "--qwen-device",
                self.args.qwen_device,
            ],
        )
        summary_path = self.output_root / "focused_eval" / run_id / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return {
            "status": "success",
            "summary": safe_path(summary_path),
            "retrieval": summary["retrieval"]["comparison"],
            "answer_policy": summary["answer_policy"]["comparison"],
            "result": result,
        }

    def run(self) -> dict[str, Any]:
        stage = self.args.stage
        result: dict[str, Any] = {"status": "success", "commit": git_text(["git", "rev-parse", "HEAD"])}
        if stage in {"preflight", "all"}:
            result["preflight"] = self.preflight()
        if self.args.process_cdc or stage == "all":
            result["cdc"] = self.cdc_status(process=True)
        if stage in {"real-document-regression", "all"}:
            result["real_document_regression"] = self.real_document_regression()
        if stage in {"answer-policy-eval", "all"}:
            result["answer_policy"] = self.answer_policy_eval()
        if stage in {"focused-eval", "all"}:
            result["focused_eval"] = self.focused_eval()
        result["warnings"] = self.warnings
        result["artifact_paths"] = self.artifacts
        return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 3 server acceptance stages with compact output.")
    parser.add_argument("--stage", choices=["preflight", "real-document-regression", "answer-policy-eval", "focused-eval", "all"], default="preflight")
    parser.add_argument("--output-root", default="outputs/evaluation/phase3_server_acceptance")
    parser.add_argument("--log-dir", default="outputs/logs/phase3_server_acceptance")
    parser.add_argument("--globocan-document-dir", default="data/real_documents/globocan_africa_2022/docagent_documents/fe3465edd3da60d2")
    parser.add_argument("--globocan-qa-path", default="data/real_documents/globocan_africa_2022/qa/scenario_qa.jsonl")
    parser.add_argument("--cdc-pdf", default="data/real_documents/cdc_135850_DS1.pdf")
    parser.add_argument("--cdc-document-root", default="data/real_documents/cdc_135850_DS1")
    parser.add_argument("--process-cdc", action="store_true")
    parser.add_argument("--mpdocvqa-reader-input", default="data/benchmark/mp_docvqa_imdb_ocr_5000_split/dev.jsonl")
    parser.add_argument("--mpdocvqa-retrieval-qa", default="outputs/evaluation/phase3_mpdocvqa_retrieval/mpdocvqa_phase3_dev_qa.jsonl")
    parser.add_argument("--mpdocvqa-retrieval-corpus", default="outputs/evaluation/phase3_mpdocvqa_retrieval/mpdocvqa_phase3_dev_corpus.jsonl")
    parser.add_argument("--bge-model-path", default="/root/autodl-tmp/models/bge-m3")
    parser.add_argument("--reranker-model-path", default="/root/autodl-tmp/models/bge-reranker-v2-m3")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--sft-adapter-path", default="outputs/checkpoints/qwen3-docagent-sft-mpdocvqa-retrieved-20260605_180454/v0-20260605-180519/checkpoint-155")
    parser.add_argument("--grpo-adapter-path", default="outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535")
    parser.add_argument("--retrieval-device", default="cuda:1")
    parser.add_argument("--qwen-device", default="cuda:0")
    parser.add_argument("--retrieval-limit", type=int, default=300)
    parser.add_argument("--answer-limit", type=int, default=150)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = 0
    try:
        payload = AcceptanceRunner(args).run()
    except Exception as exc:
        exit_code = 1
        payload = {
            "status": "failed",
            "exception": f"{type(exc).__name__}: {exc}",
            "traceback_tail": traceback.format_exc().splitlines()[-60:],
        }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
