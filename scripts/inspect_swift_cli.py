from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import shutil
import subprocess
from pathlib import Path


CHECKS = {
    "sft": [
        "--model",
        "--dataset",
        "--train_type",
        "--tuner_type",
        "--torch_dtype",
        "--num_train_epochs",
        "--per_device_train_batch_size",
        "--gradient_accumulation_steps",
        "--learning_rate",
        "--lora_rank",
        "--lora_alpha",
        "--target_modules",
        "--output_dir",
    ],
    "rlhf": [
        "--rlhf_type",
        "grpo",
        "--model",
        "--dataset",
        "--train_type",
        "--tuner_type",
        "--lora_rank",
        "--lora_alpha",
        "--target_modules",
        "--reward_funcs",
        "--external_plugins",
        "--adapters",
        "--ref_adapters",
        "--beta",
        "--use_vllm",
        "--generation_batch_size",
        "--output_dir",
    ],
}


def run_command(command: list[str], timeout: int = 30) -> dict[str, object]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return {"command": command, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def summarize_help(text: str, keys: list[str]) -> dict[str, bool]:
    lowered = text.lower()
    return {key: key.lower() in lowered for key in keys}


def first_lines(text: str, limit: int = 80) -> str:
    return "\n".join(text.splitlines()[:limit])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="outputs/logs/swift_cli_report.json")
    parser.add_argument("--head-lines", type=int, default=80)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    swift_path = shutil.which("swift")
    report: dict[str, object] = {"swift_path": swift_path, "package_versions": package_versions()}
    if swift_path is None:
        report["error"] = "swift command not found"
    else:
        top_help = run_command(["swift", "--help"], timeout=args.timeout)
        sft_help = run_command(["swift", "sft", "--help"], timeout=args.timeout)
        rlhf_help = run_command(["swift", "rlhf", "--help"], timeout=args.timeout)
        report.update(
            {
                "top_help": {
                    "returncode": top_help["returncode"],
                    "head": first_lines(str(top_help["stdout"]) + str(top_help["stderr"]), args.head_lines),
                },
                "sft": {
                    "returncode": sft_help["returncode"],
                    "contains": summarize_help(str(sft_help["stdout"]) + str(sft_help["stderr"]), CHECKS["sft"]),
                    "head": first_lines(str(sft_help["stdout"]) + str(sft_help["stderr"]), args.head_lines),
                },
                "rlhf": {
                    "returncode": rlhf_help["returncode"],
                    "contains": summarize_help(str(rlhf_help["stdout"]) + str(rlhf_help["stderr"]), CHECKS["rlhf"]),
                    "head": first_lines(str(rlhf_help["stdout"]) + str(rlhf_help["stderr"]), args.head_lines),
                },
            }
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def package_versions() -> dict[str, str | None]:
    versions = {}
    for package in ["ms-swift", "msgspec", "torch", "transformers", "accelerate", "datasets", "peft"]:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return versions


if __name__ == "__main__":
    main()
