from __future__ import annotations

import importlib.metadata as metadata
import importlib.util
import json
import traceback


PACKAGES = ["trl", "transformers", "peft", "accelerate", "torch", "vllm"]
IMPORTS = ["trl.GRPOTrainer", "trl.RLOOTrainer"]


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def import_attr(name: str) -> dict[str, object]:
    module_name, attr = name.rsplit(".", 1)
    try:
        module = __import__(module_name, fromlist=[attr])
        getattr(module, attr)
        return {"status": "ok"}
    except Exception as exc:
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback_tail": traceback.format_exc().splitlines()[-20:],
        }


def main() -> None:
    vllm_spec = importlib.util.find_spec("vllm")
    report = {
        "packages": {package: package_version(package) for package in PACKAGES},
        "vllm_spec": None if vllm_spec is None else str(vllm_spec),
        "imports": {name: import_attr(name) for name in IMPORTS},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
