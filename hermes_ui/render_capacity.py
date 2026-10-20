"""Auto-detecção de hardware e limites do motor de filas (1.0.11).

O Motor de filas (Configuração API > Motor) expõe três limites independentes:
vídeos, thumbnails e imagens de produção. Os valores manuais sobrescrevem a
auto-detecção; campos vazios/zero voltam ao automático — `detect_render_capacity()`
para vídeos (GPU+NVENC/VAAPI = 6; CPU puro = 3) e os defaults 5/3 para as
restantes filas. Workers e UI resolvem SEMPRE por `motor_limits()` — o
`settings.json` é relido a cada tick, logo a mudança aplica-se sem restart.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from typing import Any, Mapping

logger = logging.getLogger(__name__)

GPU_VIDEO_CAPACITY = 6
CPU_VIDEO_CAPACITY = 3
DEFAULT_PARALLEL_THUMBNAILS = 5
DEFAULT_PARALLEL_IMAGES = 3
_DETECTION_CACHE: dict[str, int] = {}

_HW_ENCODER_MARKERS = ("h264_nvenc", "hevc_nvenc", "h264_vaapi", "hevc_vaapi")


def _run_probe(command: list[str], timeout_seconds: int = 8) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return str(completed.stdout or "")


def _nvidia_gpu_present() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    return bool(_run_probe(["nvidia-smi", "-L"]).strip())


def _ffmpeg_hardware_encoder_present() -> bool:
    if not shutil.which("ffmpeg"):
        return False
    encoders = _run_probe(["ffmpeg", "-hide_banner", "-encoders"]).casefold()
    return any(marker in encoders for marker in _HW_ENCODER_MARKERS)


def detect_render_capacity() -> int:
    """Capacidade de render sugerida: GPU + encoder HW = 6; CPU puro = 3.

    O resultado é cacheado por processo (a sonda custa subprocessos e a UI
    renderiza a cada rerun).
    """
    cached = _DETECTION_CACHE.get("capacity")
    if cached:
        return cached
    gpu = _nvidia_gpu_present()
    hardware = _ffmpeg_hardware_encoder_present()
    capacity = GPU_VIDEO_CAPACITY if gpu and hardware else CPU_VIDEO_CAPACITY
    _DETECTION_CACHE["capacity"] = capacity
    if gpu and not hardware:
        logger.warning("[MOTOR] GPU NVIDIA detectada sem encoder HW no FFmpeg (NVENC/VAAPI); a usar capacidade de CPU (%s).", CPU_VIDEO_CAPACITY)
    return capacity


def _motor_value(motor: Mapping[str, Any], key: str, default: int) -> int:
    try:
        value = int(motor.get(key))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def motor_limits(settings: Mapping[str, Any]) -> dict[str, int]:
    """Resolve os 3 limites do motor: manual > auto-detecção/default.

    `motor.max_parallel_videos` vazio/zero/inválido → `detect_render_capacity()`;
    `motor.max_parallel_thumbnails` → 5; `motor.max_parallel_images` → 3.
    """
    motor = settings.get("motor") if isinstance(settings, Mapping) else {}
    motor = motor if isinstance(motor, Mapping) else {}
    return {
        "videos": _motor_value(motor, "max_parallel_videos", detect_render_capacity()),
        "thumbnails": _motor_value(motor, "max_parallel_thumbnails", DEFAULT_PARALLEL_THUMBNAILS),
        "images": _motor_value(motor, "max_parallel_images", DEFAULT_PARALLEL_IMAGES),
    }
