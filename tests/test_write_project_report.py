from scripts.write_project_report import (
    compact_eval_analysis,
    compact_eval_comparison,
    compact_grpo_run_summary,
    compact_reader_errors,
    compact_sft_summary,
)


def test_compact_sft_summary_keeps_reader_metrics() -> None:
    report = compact_sft_summary(
        {
            "model": "model",
            "adapter": "checkpoint",
            "input": "dev.jsonl",
            "output": "eval.jsonl",
            "num_samples": 393,
            "json_pass_rate": 1.0,
            "schema_pass_rate": 0.99,
            "thinking_rate": 0.0,
            "answer_em": 0.5,
            "answer_f1": 0.6,
            "answer_score": 0.6,
            "location_accuracy": 0.9,
            "mean_reward": 0.73,
            "extra": "drop",
        }
    )

    assert report == {
        "model": "model",
        "adapter": "checkpoint",
        "input": "dev.jsonl",
        "output": "eval.jsonl",
        "num_samples": 393,
        "json_pass_rate": 1.0,
        "schema_pass_rate": 0.99,
        "thinking_rate": 0.0,
        "answer_em": 0.5,
        "answer_f1": 0.6,
        "answer_score": 0.6,
        "location_accuracy": 0.9,
        "mean_reward": 0.73,
    }


def test_compact_reader_errors_keeps_taxonomy() -> None:
    report = compact_reader_errors(
        {
            "num_records": 393,
            "outcome_counts": {"answer_bad_location_ok": 162},
            "answer_bad_location_ok_f1": {"f1=0": 117},
            "answer_bad_location_ok_question_types": {"numeric": 79},
            "examples": {"numeric": [{"id": "1"}]},
        }
    )

    assert report == {
        "num_records": 393,
        "outcome_counts": {"answer_bad_location_ok": 162},
        "answer_bad_location_ok_f1": {"f1=0": 117},
        "answer_bad_location_ok_question_types": {"numeric": 79},
    }


def test_compact_eval_comparison_keeps_change_counts() -> None:
    report = compact_eval_comparison(
        {
            "baseline": "baseline.jsonl",
            "candidate": "strict.jsonl",
            "num_common": 393,
            "reward_delta_sum": 0.18,
            "improved_count": 9,
            "regressed_count": 11,
            "changed_answer_count": 39,
            "improved_examples": [{"id": "1"}],
        }
    )

    assert report == {
        "baseline": "baseline.jsonl",
        "candidate": "strict.jsonl",
        "num_common": 393,
        "reward_delta_sum": 0.18,
        "improved_count": 9,
        "regressed_count": 11,
        "changed_answer_count": 39,
    }


def test_compact_eval_analysis_keeps_failure_counts() -> None:
    report = compact_eval_analysis(
        {
            "num_records": 393,
            "location_value_types": {"object": 392, "missing": 1},
            "failure_counts": {"answer_em": 186, "location_ok": 42},
            "by_answer_type": {"extractive": {"answer_em:True": 207}},
            "examples": {"answer_em": [{"id": "1"}]},
        }
    )

    assert report == {
        "num_records": 393,
        "location_value_types": {"object": 392, "missing": 1},
        "failure_counts": {"answer_em": 186, "location_ok": 42},
        "by_answer_type": {"extractive": {"answer_em:True": 207}},
    }


def test_compact_grpo_run_summary_computes_training_signal() -> None:
    report = compact_grpo_run_summary(
        {
            "model": "model",
            "start_adapter": "sft",
            "dataset": "grpo.jsonl",
            "output_dir": "grpo20",
            "limit": 200,
            "max_steps": 20,
            "num_generations": 4,
            "log_history": [
                {
                    "reward": 0.95,
                    "reward_std": 0.1,
                    "loss": "0.25",
                    "completions/clipped_ratio": 0.0,
                    "completions/mean_length": 117.0,
                    "grad_norm": 0.32,
                },
                {
                    "reward": "0.85",
                    "reward_std": "0.17",
                    "loss": -0.06,
                    "completions/clipped_ratio": "0.0",
                    "completions/mean_length": "102",
                    "grad_norm": "0.16",
                },
            ],
        }
    )

    assert report["logged_steps"] == 2
    assert report["nonzero_reward_std_steps"] == 2
    assert report["reward"]["first"] == 0.95
    assert report["reward"]["last"] == 0.85
    assert report["max_completion_clipped_ratio"] == 0.0
    assert report["max_grad_norm"] == 0.32
