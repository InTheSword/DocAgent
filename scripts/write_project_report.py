from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compact_audit(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "num_records": report.get("num_records"),
        "clean_records": report.get("clean_records"),
        "clean_rate": report.get("clean_rate"),
        "issue_counts": report.get("issue_counts", {}),
        "by_answer_type": report.get("by_answer_type", {}),
    }


def compact_retrieval(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "input": report.get("input"),
        "num_samples": report.get("num_samples"),
        "num_blocks": report.get("num_blocks"),
        "top_k": report.get("top_k"),
        "candidate_scope": report.get("candidate_scope"),
        "recall_at_k": report.get("recall_at_k"),
        "mrr_at_k": report.get("mrr_at_k"),
        "num_misses": report.get("num_misses"),
    }


def compact_sft_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "model": report.get("model"),
        "adapter": report.get("adapter"),
        "input": report.get("input"),
        "output": report.get("output"),
        "num_samples": report.get("num_samples"),
        "json_pass_rate": report.get("json_pass_rate"),
        "schema_pass_rate": report.get("schema_pass_rate"),
        "thinking_rate": report.get("thinking_rate"),
        "answer_em": report.get("answer_em"),
        "answer_f1": report.get("answer_f1"),
        "answer_score": report.get("answer_score"),
        "location_accuracy": report.get("location_accuracy"),
        "mean_reward": report.get("mean_reward"),
    }


def compact_reader_errors(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "num_records": report.get("num_records"),
        "outcome_counts": report.get("outcome_counts", {}),
        "answer_bad_location_ok_f1": report.get("answer_bad_location_ok_f1", {}),
        "answer_bad_location_ok_question_types": report.get("answer_bad_location_ok_question_types", {}),
    }


def compact_eval_comparison(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "baseline": report.get("baseline"),
        "candidate": report.get("candidate"),
        "num_common": report.get("num_common"),
        "reward_delta_sum": report.get("reward_delta_sum"),
        "improved_count": report.get("improved_count"),
        "regressed_count": report.get("regressed_count"),
        "changed_answer_count": report.get("changed_answer_count"),
    }


def compact_eval_analysis(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "num_records": report.get("num_records"),
        "location_value_types": report.get("location_value_types", {}),
        "failure_counts": report.get("failure_counts", {}),
        "by_answer_type": report.get("by_answer_type", {}),
    }


def numeric_values(history: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in history:
        value = row.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
            continue
        if isinstance(value, str):
            try:
                values.append(float(value))
            except ValueError:
                pass
    return values


def first_last_mean(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"first": None, "last": None, "mean": None}
    return {"first": values[0], "last": values[-1], "mean": sum(values) / len(values)}


def compact_grpo_run_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    history = report.get("log_history") or []
    reward_std = numeric_values(history, "reward_std")
    rewards = numeric_values(history, "reward")
    losses = numeric_values(history, "loss")
    clipped_ratios = numeric_values(history, "completions/clipped_ratio")
    mean_lengths = numeric_values(history, "completions/mean_length")
    grad_norms = numeric_values(history, "grad_norm")
    return {
        "model": report.get("model"),
        "start_adapter": report.get("start_adapter"),
        "dataset": report.get("dataset"),
        "output_dir": report.get("output_dir"),
        "limit": report.get("limit"),
        "max_steps": report.get("max_steps"),
        "num_generations": report.get("num_generations"),
        "logged_steps": len(history),
        "nonzero_reward_std_steps": sum(value > 1e-6 for value in reward_std),
        "reward": first_last_mean(rewards),
        "reward_std": first_last_mean(reward_std),
        "loss": first_last_mean(losses),
        "completion_clipped_ratio": first_last_mean(clipped_ratios),
        "completion_mean_length": first_last_mean(mean_lengths),
        "max_completion_clipped_ratio": max(clipped_ratios) if clipped_ratios else None,
        "max_grad_norm": max(grad_norms) if grad_norms else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reports/docagent_project_report.json")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    root = Path(args.repo_root)
    report = {
        "data_quality": {
            "mp_docvqa_train_sft_clean": compact_audit(
                load_json(root / "outputs/eval/mp_docvqa_train_sft_clean_audit.json")
            ),
            "mp_docvqa_dev_sft_clean": compact_audit(
                load_json(root / "outputs/eval/mp_docvqa_dev_sft_clean_audit.json")
            ),
            "mp_docvqa_train_grpo": compact_audit(load_json(root / "outputs/eval/mp_docvqa_train_grpo_audit.json")),
        },
        "retrieval": {
            "mp_docvqa_dev_same_doc_bm25": compact_retrieval(
                load_json(root / "outputs/eval/mp_docvqa_dev_retrieval_same_doc.json")
            ),
            "mp_docvqa_test_same_doc_bm25": compact_retrieval(
                load_json(root / "outputs/eval/mp_docvqa_test_retrieval_same_doc.json")
            ),
        },
        "sft_reader": {
            "mp_docvqa_retrieved_1024": compact_sft_summary(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_full_eval_1024_summary.json")
            ),
            "mp_docvqa_retrieved_1024_strict": compact_sft_summary(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_full_eval_1024_strict_summary.json")
            ),
            "mp_docvqa_retrieved_1024_vs_strict": compact_eval_comparison(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_1024_vs_strict_compare.json")
            ),
            "mp_docvqa_retrieved_1024_reader_errors": compact_reader_errors(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_full_eval_1024_reader_errors.json")
            ),
        },
        "grpo_reader": {
            "mp_docvqa_train_grpo_retrieved": compact_audit(
                load_json(root / "outputs/eval/mp_docvqa_train_grpo_retrieved_audit.json")
            ),
            "mp_docvqa_retrieved_grpo20_train": compact_grpo_run_summary(
                load_json(root / "outputs/eval/qwen3-docagent-trl-grpo-ng4-20260606_093651_summary.json")
            ),
            "mp_docvqa_retrieved_grpo20_eval": compact_sft_summary(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grpo20_eval_1024_summary.json")
            ),
            "mp_docvqa_retrieved_grpo20_analysis": compact_eval_analysis(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grpo20_eval_1024_analysis.json")
            ),
            "mp_docvqa_retrieved_sft_vs_grpo20": compact_eval_comparison(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_sft_vs_grpo20_compare.json")
            ),
            "mp_docvqa_retrieved_grpo100_train": compact_grpo_run_summary(
                load_json(
                    root
                    / "outputs/eval/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-100step-20260606_100045_summary.json"
                )
            ),
            "mp_docvqa_retrieved_grpo100_eval": compact_sft_summary(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grpo100_eval_1024_summary.json")
            ),
            "mp_docvqa_retrieved_grpo100_analysis": compact_eval_analysis(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grpo100_eval_1024_analysis.json")
            ),
            "mp_docvqa_retrieved_sft_vs_grpo100": compact_eval_comparison(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_sft_vs_grpo100_compare.json")
            ),
            "mp_docvqa_retrieved_grpo20_vs_grpo100": compact_eval_comparison(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grpo20_vs_grpo100_compare.json")
            ),
            "mp_docvqa_retrieved_1024_grounded_reward": compact_sft_summary(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_full_eval_1024_grounded_reward_summary.json")
            ),
            "mp_docvqa_retrieved_grpo100_grounded_reward": compact_sft_summary(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grpo100_eval_1024_grounded_reward_summary.json")
            ),
            "mp_docvqa_retrieved_grounded_grpo100_train": compact_grpo_run_summary(
                load_json(
                    root
                    / "outputs/eval/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535_summary.json"
                )
            ),
            "mp_docvqa_retrieved_grounded_grpo100_eval": compact_sft_summary(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grounded_grpo100_eval_1024_summary.json")
            ),
            "mp_docvqa_retrieved_grounded_grpo100_analysis": compact_eval_analysis(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grounded_grpo100_eval_1024_analysis.json")
            ),
            "mp_docvqa_retrieved_sft_vs_grounded_grpo100": compact_eval_comparison(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_sft_vs_grounded_grpo100_compare.json")
            ),
            "mp_docvqa_retrieved_grpo100_vs_grounded_grpo100": compact_eval_comparison(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_old_grpo100_vs_grounded_grpo100_compare.json")
            ),
            "mp_docvqa_retrieved_grounded_grpo_full500_train": compact_grpo_run_summary(
                load_json(
                    root
                    / "outputs/eval/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-full500-100step-20260606_113406_summary.json"
                )
            ),
            "mp_docvqa_retrieved_grounded_grpo_full500_eval": compact_sft_summary(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grounded_grpo_full500_eval_1024_summary.json")
            ),
            "mp_docvqa_retrieved_grounded_grpo_full500_analysis": compact_eval_analysis(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_grounded_grpo_full500_eval_1024_analysis.json")
            ),
            "mp_docvqa_retrieved_sft_vs_grounded_grpo_full500": compact_eval_comparison(
                load_json(root / "outputs/eval/sft_mpdocvqa_retrieved_sft_vs_grounded_grpo_full500_compare.json")
            ),
        },
    }

    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "sections": list(report)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
