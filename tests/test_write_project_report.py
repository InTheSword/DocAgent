from scripts.write_project_report import compact_eval_comparison, compact_reader_errors, compact_sft_summary


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
