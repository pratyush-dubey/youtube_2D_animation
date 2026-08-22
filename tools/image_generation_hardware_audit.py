"""Write the local image-generation hardware audit required before model selection."""
from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "output" / "hardware"


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def command(args, timeout=20):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return (result.stdout or result.stderr).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def memory():
    status = MEMORYSTATUSEX(); status.dwLength = ctypes.sizeof(status)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {"physical_total_gb": round(status.ullTotalPhys / 2**30, 2), "physical_available_gb": round(status.ullAvailPhys / 2**30, 2)}
    return {"physical_total_gb": None, "physical_available_gb": None}


def disk(letter):
    root = f"{letter}:\\"
    if not Path(root).exists(): return {"present": False}
    usage = shutil.disk_usage(root)
    return {"present": True, "total_gb": round(usage.total/2**30, 2), "free_gb": round(usage.free/2**30, 2)}


def dxdiag(report_dir):
    path = report_dir / "dxdiag.txt"
    subprocess.run(["dxdiag", "/whql:off", "/t", str(path)], timeout=90, check=False)
    if not path.exists(): return {"status": "unavailable"}
    text = path.read_text(encoding="utf-16", errors="ignore") if path.read_bytes()[:2] in {b"\xff\xfe", b"\xfe\xff"} else path.read_text(errors="ignore")
    def fields(label):
        values = re.findall(rf"^\s*{re.escape(label)}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
        return list(dict.fromkeys(value.strip() for value in values))
    return {
        "status": "available", "card_names": fields("Card name"), "manufacturers": fields("Manufacturer"),
        "display_memory": fields("Display Memory"), "dedicated_memory": fields("Dedicated Memory"),
        "shared_memory": fields("Shared Memory"), "directx_version": fields("DirectX Version"),
        "feature_levels": fields("Feature Levels"), "driver_models": fields("Driver Model"),
        "driver_versions": fields("Driver Version"),
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    dx = dxdiag(REPORT_DIR)
    nvidia = shutil.which("nvidia-smi")
    vulkan = shutil.which("vulkaninfo")
    torch_present = importlib.util.find_spec("torch") is not None
    cuda = {"available": False, "torch_present": torch_present}
    if torch_present:
        try:
            import torch
            cuda.update({"available": bool(torch.cuda.is_available()), "torch_version": torch.__version__, "cuda_version": torch.version.cuda})
        except Exception as exc: cuda["error"] = str(exc)
    report = {
        "audit_version": 1, "platform": platform.platform(), "windows_version": platform.version(),
        "cpu": {"name": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", ""), "logical_threads": os.cpu_count()},
        "memory": memory(), "gpu": dx, "cuda": cuda,
        "directml": {
            "python_runtime_installed": importlib.util.find_spec("torch_directml") is not None,
            "hardware_d3d12_capable": any("12_" in value for value in dx.get("feature_levels", [])),
            "note": "D3D12 capability permits DirectML in principle; the Python runtime/backend must still be installed and benchmarked.",
        },
        "vulkan": {
            "vulkaninfo_installed": bool(vulkan),
            "summary": command([vulkan, "--summary"], 30) if vulkan else "vulkaninfo not installed; capability not yet benchmarked",
        },
        "disk": {"C": disk("C"), "D": disk("D")},
        "software": {
            "python": sys.version.split()[0], "python_executable": sys.executable,
            "git": command(["git", "--version"]), "ffmpeg": command(["ffmpeg", "-version"]).splitlines()[0],
            "blender": command([str(Path("C:/Program Files/Blender Foundation/Blender 5.2/blender.exe")), "--version"]).splitlines()[0],
            "nvidia_smi": nvidia or "not installed",
        },
    }
    report["classification"] = {
        "cuda_class": "none" if not cuda["available"] else "available",
        "likely_primary_acceleration": "DirectML" if report["directml"]["hardware_d3d12_capable"] else "CPU",
        "large_model_download_allowed": False,
        "reason": "Model selection and license review must complete before any model download.",
    }
    path = REPORT_DIR / "image_generation_hardware_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)); print(path)


if __name__ == "__main__": main()
