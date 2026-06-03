from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/root/autodl-tmp/models/Qwen3-1.7B")
    args = parser.parse_args()

    model_dir = Path(args.model)
    result: dict[str, object] = {
        "model": str(model_dir),
        "exists": model_dir.exists(),
        "is_dir": model_dir.is_dir(),
    }

    required = ["config.json"]
    missing = [name for name in required if not (model_dir / name).is_file()]
    result["missing_required_files"] = missing

    weight_files = sorted(
        [
            path.name
            for pattern in ("*.safetensors", "*.bin")
            for path in model_dir.glob(pattern)
        ]
    )
    index_files = sorted(path.name for path in model_dir.glob("*.index.json"))
    result["num_weight_files"] = len(weight_files)
    result["weight_files_head"] = weight_files[:8]
    result["index_files"] = index_files

    try:
        from transformers import AutoConfig, AutoTokenizer

        config = AutoConfig.from_pretrained(
            str(model_dir),
            local_files_only=True,
            trust_remote_code=True,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            str(model_dir),
            local_files_only=True,
            trust_remote_code=True,
        )
        result["transformers_load"] = {
            "ok": True,
            "model_type": getattr(config, "model_type", None),
            "architectures": getattr(config, "architectures", None),
            "vocab_size": getattr(tokenizer, "vocab_size", None),
        }
    except Exception as exc:  # noqa: BLE001 - surface exact local model issue.
        result["transformers_load"] = {
            "ok": False,
            "error": repr(exc),
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if missing or not result["transformers_load"]["ok"] or len(weight_files) == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
