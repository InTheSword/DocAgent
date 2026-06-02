from __future__ import annotations

import importlib.metadata as metadata
import json
import subprocess
import sys
from pathlib import Path


PACKAGES = [
    "torch",
    "torchvision",
    "torchaudio",
    "transformers",
    "accelerate",
    "datasets",
    "peft",
    "ms-swift",
    "gradio",
    "gradio-client",
    "hf-gradio",
    "fastapi",
    "starlette",
    "pydantic",
    "langgraph",
    "sentence-transformers",
    "faiss-cpu",
    "rank-bm25",
    "deepspeed",
    "mineru",
]


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def pip_check() -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def main() -> None:
    report = {
        "python": sys.version,
        "executable": sys.executable,
        "cwd": str(Path.cwd()),
        "packages": {name: package_version(name) for name in PACKAGES},
        "pip_check": pip_check(),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

