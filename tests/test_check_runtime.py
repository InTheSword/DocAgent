from __future__ import annotations

from scripts.check_runtime import classify_resource_mode, compact_report


def test_classify_resource_mode_gpu_visible() -> None:
    assert (
        classify_resource_mode(
            {"available": True, "cuda_available": True, "device_count": 1},
            {"device_files": ["/dev/nvidia0"], "proc_driver_nvidia": True},
        )
        == "gpu_visible"
    )


def test_classify_resource_mode_no_card_or_cpu() -> None:
    assert (
        classify_resource_mode(
            {"available": True, "cuda_available": False, "device_count": 0},
            {"device_files": [], "proc_driver_nvidia": False},
        )
        == "no_card_or_cpu"
    )


def test_classify_resource_mode_driver_visible_but_torch_cpu() -> None:
    assert (
        classify_resource_mode(
            {"available": True, "cuda_available": False, "device_count": 0},
            {"device_files": ["/dev/nvidiactl"], "proc_driver_nvidia": True},
        )
        == "gpu_driver_visible_torch_cpu"
    )


def test_compact_report_keeps_routing_fields_without_full_nvidia_smi() -> None:
    report = {
        "command": "check_runtime",
        "status": "success",
        "resource_mode": "gpu_visible",
        "gpu_visible": True,
        "gpu_unavailable_for_torch": False,
        "cuda_visible_devices": "0",
        "torch": {
            "available": True,
            "torch_version": "2.12.0",
            "cuda_available": True,
            "cuda_version": "13.0",
            "device_count": 1,
            "devices": [{"index": 0, "name": "GPU", "total_memory_gb": 24.0}],
        },
        "gpu_visibility": {
            "device_files": ["/dev/nvidia0", "/dev/nvidiactl"],
            "proc_driver_nvidia": True,
            "which_nvidia_smi": "/usr/bin/nvidia-smi",
        },
        "nvidia_smi": "large table omitted",
    }

    compact = compact_report(report)

    assert compact == {
        "command": "check_runtime",
        "status": "success",
        "resource_mode": "gpu_visible",
        "gpu_visible": True,
        "gpu_unavailable_for_torch": False,
        "torch_available": True,
        "torch_version": "2.12.0",
        "torch_cuda_available": True,
        "torch_cuda_version": "13.0",
        "torch_device_count": 1,
        "torch_devices": [{"index": 0, "name": "GPU", "total_memory_gb": 24.0}],
        "cuda_visible_devices": "0",
        "nvidia_device_file_count": 2,
        "proc_driver_nvidia": True,
        "which_nvidia_smi": "/usr/bin/nvidia-smi",
    }
    assert "nvidia_smi" not in compact
