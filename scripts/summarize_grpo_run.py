from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def numeric_values(history: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in history:
        value = row.get(key)
        if isinstance(value, int | float):
            values.append(float(value))
    return values


def first_last(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"first": None, "last": None, "mean": None}
    return {"first": values[0], "last": values[-1], "mean": mean(values)}


def max_value(values: list[float]) -> float | None:
    return max(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--log-file", default=None)
    args = parser.parse_args()

    summary_path = ROOT / args.input
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    history = summary.get("log_history") or []
    reward_std = numeric_values(history, "reward_std")
    rewards = numeric_values(history, "reward")
    losses = numeric_values(history, "loss")
    grad_norms = numeric_values(history, "grad_norm")
    clipped_ratios = numeric_values(history, "completions/clipped_ratio")
    mean_lengths = numeric_values(history, "completions/mean_length")

    report = {
        "summary": args.input,
        "output_dir": summary.get("output_dir"),
        "limit": summary.get("limit"),
        "max_steps": summary.get("max_steps"),
        "num_generations": summary.get("num_generations"),
        "logged_steps": len(history),
        "nonzero_reward_std_steps": sum(value > 1e-6 for value in reward_std),
        "reward": first_last(rewards),
        "reward_std": first_last(reward_std),
        "loss": first_last(losses),
        "completion_clipped_ratio": first_last(clipped_ratios),
        "completion_mean_length": first_last(mean_lengths),
        "max_completion_clipped_ratio": max_value(clipped_ratios),
        "max_grad_norm": max(grad_norms) if grad_norms else None,
    }
    if args.log_file:
        report["log_file"] = args.log_file
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
