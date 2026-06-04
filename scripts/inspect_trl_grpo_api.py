from __future__ import annotations

import importlib.metadata as metadata
import inspect
import json


def safe_signature(obj: object) -> str:
    try:
        return str(inspect.signature(obj))
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def main() -> None:
    from trl import GRPOConfig, GRPOTrainer

    report = {
        "versions": {
            package: _version(package)
            for package in ["trl", "transformers", "peft", "accelerate", "torch", "datasets", "vllm"]
        },
        "GRPOConfig_signature": safe_signature(GRPOConfig),
        "GRPOTrainer_signature": safe_signature(GRPOTrainer),
        "GRPOConfig_key_defaults": _config_defaults(GRPOConfig),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _config_defaults(config_cls: type) -> dict[str, object]:
    signature = inspect.signature(config_cls)
    keys = [
        "output_dir",
        "per_device_train_batch_size",
        "gradient_accumulation_steps",
        "learning_rate",
        "max_steps",
        "bf16",
        "gradient_checkpointing",
        "max_prompt_length",
        "max_completion_length",
        "num_generations",
        "temperature",
        "top_p",
        "use_vllm",
        "beta",
        "save_steps",
        "save_total_limit",
        "logging_steps",
        "report_to",
        "remove_unused_columns",
    ]
    defaults: dict[str, object] = {}
    for key in keys:
        parameter = signature.parameters.get(key)
        if parameter is None:
            defaults[key] = "<missing>"
        elif parameter.default is inspect.Parameter.empty:
            defaults[key] = "<required>"
        else:
            defaults[key] = repr(parameter.default)
    return defaults


if __name__ == "__main__":
    main()
