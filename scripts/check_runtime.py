from __future__ import annotations

import json
import os
import platform
import subprocess
import sys


def command_output(command: list[str], timeout: int = 3) -> str | None:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    output = (completed.stdout or completed.stderr or "").strip()
    return output or None


def torch_info() -> dict[str, object]:
    try:
        import torch
    except Exception as exc:
        return {"available": False, "error": str(exc)}

    info: dict[str, object] = {
        "available": True,
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        "bf16_supported": False,
        "devices": [],
    }
    if torch.cuda.is_available():
        info["bf16_supported"] = bool(torch.cuda.is_bf16_supported())
        devices = []
        for idx in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(idx)
            devices.append(
                {
                    "index": idx,
                    "name": props.name,
                    "total_memory_gb": round(props.total_memory / 1024**3, 2),
                    "major": props.major,
                    "minor": props.minor,
                }
            )
        info["devices"] = devices
    return info


def main() -> None:
    report = {
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": os.getcwd(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "torch": torch_info(),
        "nvidia_smi": command_output(["nvidia-smi"]),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
