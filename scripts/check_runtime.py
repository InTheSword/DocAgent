from __future__ import annotations

import json
import os
import platform
import glob
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

    cuda_available = torch.cuda.is_available()
    device_count = 0
    cuda_init_error = None
    try:
        device_count = torch.cuda.device_count()
    except Exception as exc:
        cuda_init_error = str(exc)

    info: dict[str, object] = {
        "available": True,
        "torch_version": torch.__version__,
        "cuda_available": cuda_available,
        "cuda_version": torch.version.cuda,
        "device_count": device_count,
        "bf16_supported": False,
        "devices": [],
        "cuda_init_error": cuda_init_error,
    }
    if cuda_available:
        try:
            info["bf16_supported"] = bool(torch.cuda.is_bf16_supported())
        except Exception as exc:
            info["bf16_supported_error"] = str(exc)
        devices = []
        for idx in range(device_count):
            try:
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
            except Exception as exc:
                devices.append({"index": idx, "error": str(exc)})
        info["devices"] = devices
    return info


def gpu_visibility_info() -> dict[str, object]:
    return {
        "env": {
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "NVIDIA_VISIBLE_DEVICES": os.environ.get("NVIDIA_VISIBLE_DEVICES"),
            "NVIDIA_DRIVER_CAPABILITIES": os.environ.get("NVIDIA_DRIVER_CAPABILITIES"),
            "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH"),
        },
        "device_files": sorted(glob.glob("/dev/nvidia*")),
        "proc_driver_nvidia": os.path.exists("/proc/driver/nvidia/version"),
        "proc_driver_nvidia_version": command_output(["cat", "/proc/driver/nvidia/version"]),
        "which_nvidia_smi": command_output(["which", "nvidia-smi"]),
        "ldconfig_cuda": command_output(["bash", "-lc", "ldconfig -p | grep -E 'libcuda|libnvidia-ml' | head -20"]),
    }


def main() -> None:
    report = {
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": os.getcwd(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "torch": torch_info(),
        "gpu_visibility": gpu_visibility_info(),
        "nvidia_smi": command_output(["nvidia-smi"]),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
