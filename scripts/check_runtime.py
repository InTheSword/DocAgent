from __future__ import annotations

import argparse
import json
import os
import platform
import glob
import subprocess
import sys
from typing import Any


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


def classify_resource_mode(torch_payload: dict[str, Any], gpu_payload: dict[str, Any]) -> str:
    if not torch_payload.get("available"):
        return "torch_unavailable"
    cuda_available = bool(torch_payload.get("cuda_available"))
    device_count = int(torch_payload.get("device_count") or 0)
    if cuda_available and device_count > 0:
        return "gpu_visible"
    if cuda_available and device_count <= 0:
        return "cuda_inconsistent"
    device_files = gpu_payload.get("device_files") or []
    driver_visible = bool(gpu_payload.get("proc_driver_nvidia") or device_files)
    if driver_visible:
        return "gpu_driver_visible_torch_cpu"
    return "no_card_or_cpu"


def build_report(*, include_nvidia_smi: bool = True) -> dict[str, Any]:
    torch_payload = torch_info()
    gpu_payload = gpu_visibility_info()
    resource_mode = classify_resource_mode(torch_payload, gpu_payload)
    report = {
        "command": "check_runtime",
        "status": "success",
        "resource_mode": resource_mode,
        "gpu_visible": resource_mode == "gpu_visible",
        "gpu_unavailable_for_torch": resource_mode != "gpu_visible",
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": os.getcwd(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "torch": torch_payload,
        "gpu_visibility": gpu_payload,
    }
    if include_nvidia_smi:
        report["nvidia_smi"] = command_output(["nvidia-smi"])
    return report


def compact_report(report: dict[str, Any]) -> dict[str, Any]:
    torch_payload = report.get("torch") if isinstance(report.get("torch"), dict) else {}
    gpu_payload = report.get("gpu_visibility") if isinstance(report.get("gpu_visibility"), dict) else {}
    return {
        "command": report.get("command", "check_runtime"),
        "status": report.get("status", "success"),
        "resource_mode": report.get("resource_mode"),
        "gpu_visible": bool(report.get("gpu_visible")),
        "gpu_unavailable_for_torch": bool(report.get("gpu_unavailable_for_torch")),
        "torch_available": bool(torch_payload.get("available")),
        "torch_version": torch_payload.get("torch_version"),
        "torch_cuda_available": bool(torch_payload.get("cuda_available")),
        "torch_cuda_version": torch_payload.get("cuda_version"),
        "torch_device_count": int(torch_payload.get("device_count") or 0),
        "torch_devices": torch_payload.get("devices") or [],
        "cuda_visible_devices": report.get("cuda_visible_devices"),
        "nvidia_device_file_count": len(gpu_payload.get("device_files") or []),
        "proc_driver_nvidia": bool(gpu_payload.get("proc_driver_nvidia")),
        "which_nvidia_smi": gpu_payload.get("which_nvidia_smi"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Python, Torch, and GPU visibility without loading project models.")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON for server mode routing.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = build_report(include_nvidia_smi=not args.compact)
    if args.compact:
        report = compact_report(report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
