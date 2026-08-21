"""Report local animation hardware and select a zero-cost 3D strategy."""
from __future__ import annotations

import json
import argparse
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def _run(command: list[str]) -> str:
    try:
        return subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=15
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _powershell(script: str) -> str:
    return _run(["powershell", "-NoProfile", "-Command", script])


@dataclass(frozen=True)
class HardwareProfile:
    cpu: str
    cpu_cores: int
    cpu_threads: int
    ram_gb: float
    gpu: str
    vram_gb: float
    cuda_available: bool
    cuda_version: str
    disk_free_gb: float
    disk_path: str
    python_version: str
    blender_version: str
    ffmpeg_version: str
    ollama_version: str
    ollama_models: tuple[str, ...]
    model_class: str
    selected_strategy: str
    selection_reason: str


def collect_hardware_profile() -> HardwareProfile:
    root = Path.cwd().anchor or os.getcwd()
    disk = shutil.disk_usage(root)
    cpu_raw = _powershell(
        "Get-CimInstance Win32_Processor | Select-Object -First 1 "
        "-ExpandProperty Name"
    )
    cores_raw = _powershell(
        "$x=Get-CimInstance Win32_Processor | Select-Object -First 1; "
        "Write-Output ($x.NumberOfCores.ToString()+'|'+$x.NumberOfLogicalProcessors.ToString())"
    )
    gpu_raw = _powershell(
        "$x=Get-CimInstance Win32_VideoController | Select-Object -First 1; "
        "Write-Output ($x.Name+'|'+$x.AdapterRAM)"
    )
    ram_raw = _powershell(
        "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"
    )
    cores = cores_raw.split("|") if "|" in cores_raw else []
    gpu = gpu_raw.split("|") if "|" in gpu_raw else []
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        cuda_version = str(torch.version.cuda or "")
    except ImportError:
        cuda_available = False
        cuda_version = ""
    blender = shutil.which("blender") or ""
    if not blender:
        candidates = sorted(Path("C:/Program Files/Blender Foundation").glob("Blender */blender.exe"))
        blender = str(candidates[-1]) if candidates else ""
    blender_version = _run([blender, "--version"]).splitlines()[0] if blender else "not found"
    ffmpeg_version = _run(["ffmpeg", "-version"]).splitlines()
    ollama_version = _run(["ollama", "--version"])
    ollama_lines = _run(["ollama", "list"]).splitlines()[1:]
    ram_gb = round(int(ram_raw or 0) / 1024**3, 2)
    vram_gb = round(int(gpu[1] or 0) / 1024**3, 2) if len(gpu) > 1 else 0.0
    model_class = "HEAVY" if cuda_available and vram_gb >= 16 else "MEDIUM" if cuda_available and vram_gb >= 8 else "LIGHT"
    strategy = "local_diffusion_illustration" if model_class != "LIGHT" else "cinematic_2d25d_existing_assets"
    reason = (
        "CUDA hardware can support a local illustration model."
        if model_class != "LIGHT"
        else (
            "No CUDA GPU with sufficient VRAM; do not download a large diffusion model. "
            "Use approved cached artwork or assisted masks until a suitable image provider is configured."
        )
    )
    return HardwareProfile(
        cpu=cpu_raw or platform.processor() or "unknown",
        cpu_cores=int(cores[0]) if cores else (os.cpu_count() or 0),
        cpu_threads=int(cores[1]) if len(cores) > 1 else (os.cpu_count() or 0),
        ram_gb=ram_gb,
        gpu=gpu[0] if gpu else "unknown",
        vram_gb=vram_gb,
        cuda_available=cuda_available,
        cuda_version=cuda_version,
        disk_free_gb=round(disk.free / 1024**3, 2),
        disk_path=root,
        python_version=sys.version.split()[0],
        blender_version=blender_version,
        ffmpeg_version=ffmpeg_version[0] if ffmpeg_version else "not found",
        ollama_version=ollama_version or "not found",
        ollama_models=tuple(line.split()[0] for line in ollama_lines if line.strip()),
        model_class=model_class,
        selected_strategy=strategy,
        selection_reason=reason,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(asdict(collect_hardware_profile()), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
