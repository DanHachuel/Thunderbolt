"""1.0.54 — GPU FORÇADA na montagem de clipes (fim do resize em Python).

O utilizador reportou um vídeo Pexels travado em 76% por 12+ minutos com a
GPU a 5% (idle). O diagnóstico PROVADO nesta máquina (benchmarks reais):

- MoviePy (`preprocess_video` do motor) redimensiona cada clipe em
  numpy/Python: **10,14 s** por clipe de 5 s (720p→1080p) → 97 clipes ≈
  16 min de compositing CPU com a GPU parada (só o encode a toca nela);
- o mesmo clipe pelo caminho FFmpeg externo (`-hwaccel cuda` + decode
  NVDEC + `scale` SIMD em C + `h264_nvenc`): **0,87 s**;
- injectar `-hwaccel cuda` DENTRO do `write_videofile` do MoviePy **quebra
  o pipe raw** (`OSError: [Errno 22] Invalid argument` em
  `proc.stdin.write`) — o MoviePy alimenta frames crus ao ffmpeg;
- `scale_cuda` **falha nesta combinação** (GTX 1050 Ti + ffmpeg 7.1):
  «Impossible to convert between … Parsed_scale_cuda_0 and auto_scale_0»
  com `-pix_fmt yuv420p`, rc -40 — fica documentado para ninguém o
  "corrigir" de volta.

Contratos cobertos por este ficheiro:
- a fase FFmpeg de clipes decide AUTO-ON quando há GPU REAL (nvidia-smi +
  probe NVENC), mesmo com o toggle das Configurações em OFF — quem tem
  placa NVIDIA não pode pagar o resize em Python (1.0.41 mantém o toggle
  ON a forçar sempre; rota `local` nunca é tocada);
- a normalização GPU usa `-hwaccel cuda` no decode e `scale` em C (não
  `scale_cuda`, provado quebrado), com `h264_nvenc` + fallback CPU que
  nunca perde o original;
- o watcher do motor falha rápido em «video codec h264_nvenc failed»;
- o patch de runtime injecta só params SEGUROS nos writes de hardware
  (`-pix_fmt yuv420p`, threads) — nunca hwaccel no pipe do MoviePy.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MPT_AGENT = _load_module(ROOT / "seed" / "skills" / "mpt_agent.py", "mpt_agent_gpu_encode")
PATCH = _load_module(ROOT / "seed" / "skills" / "mpt_runtime_patch.py", "mpt_runtime_patch_gpu_encode")
MPT_AGENT_SOURCE = (ROOT / "seed" / "skills" / "mpt_agent.py").read_text(encoding="utf-8")


def _write_config(root: Path, *, preprocess: bool | None = None, ffmpeg_path: str = "") -> Path:
    config_path = root / "config.toml"
    lines = ["[app]"]
    if ffmpeg_path:
        lines.append(f"ffmpeg_path = {json.dumps(ffmpeg_path)}")
    if preprocess is not None:
        lines.append(f"ffmpeg_preprocess_clips = {'true' if preprocess else 'false'}")
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path


# ---------------------------------------------------------------------------
# Decisão da fase de clipes: AUTO-ON com GPU (o contrato que destrava o 76%)
# ---------------------------------------------------------------------------


def test_preprocess_auto_on_with_gpu_even_when_toggle_is_off(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path, preprocess=False, ffmpeg_path="ffmpeg-7.1")
    monkeypatch.setattr(MPT_AGENT, "_gpu_clips_available", lambda _path: True)
    assert MPT_AGENT._should_preprocess_clips(config, "ffmpeg-7.1", "pexels") is True
    # GPU ausente + toggle OFF => fluxo antigo (respeita a máquina sem placa).
    monkeypatch.setattr(MPT_AGENT, "_gpu_clips_available", lambda _path: False)
    assert MPT_AGENT._should_preprocess_clips(config, "ffmpeg-7.1", "pexels") is False


def test_preprocess_toggle_on_still_forces_without_gpu(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path, preprocess=True, ffmpeg_path="ffmpeg-7.1")
    monkeypatch.setattr(MPT_AGENT, "_gpu_clips_available", lambda _path: False)
    assert MPT_AGENT._should_preprocess_clips(config, "ffmpeg-7.1", "pixabay") is True


def test_preprocess_never_touches_local_route(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path, preprocess=True, ffmpeg_path="ffmpeg-7.1")
    monkeypatch.setattr(MPT_AGENT, "_gpu_clips_available", lambda _path: True)
    assert MPT_AGENT._should_preprocess_clips(config, "ffmpeg-7.1", "local") is False


def test_preprocess_gpu_requires_real_probe_not_encoder_advertising():
    # 1.0.54 não enfraquece o gate: nvidia-smi + probe REAL continuam
    # obrigatórios (anunciar NVENC sem abrir não conta — lição 1.0.23).
    gpu_body = MPT_AGENT_SOURCE.split("def _gpu_clips_available", 1)[1].split(
        "def _clip_target_size", 1
    )[0]
    assert 'shutil.which("nvidia-smi")' in gpu_body
    assert "_probe_nvenc_encoder(ffmpeg_path)" in gpu_body
    assert "-encoders" not in gpu_body


def test_generate_video_uses_the_gpu_decision(tmp_path: Path, monkeypatch):
    # Fonte: a decisão passou a ser única (_should_preprocess_clips), chamada
    # com o binário FFmpeg efectivo do render (alimenta o probe de GPU).
    assert "preprocess_clips = _should_preprocess_clips(" in MPT_AGENT_SOURCE
    assert "config_path, render_ffmpeg, selected_video_source(forwarded_args)" in MPT_AGENT_SOURCE


# ---------------------------------------------------------------------------
# Normalização dos clipes: CUDA no decode + scale em C (não scale_cuda)
# ---------------------------------------------------------------------------


def test_normalize_clip_command_uses_cuda_decode_and_nvenc_first(tmp_path: Path, monkeypatch):
    commands: list[list[str]] = []
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"mp4")
    temporary = tmp_path / "clip.prep-tmp.mp4"

    class _Done:
        returncode = 0

    def fake_run(command, **_kwargs):
        commands.append(list(command))
        # Simula o sucesso do encode GPU escrevendo o temporário.
        if temporary.name in str(command[-1]) and not temporary.exists():
            temporary.write_bytes(b"preparado")
        return _Done()

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    ok, codec = MPT_AGENT._normalize_clip_with_ffmpeg(
        "ffmpeg-7.1", source, 1920, 1080, gpu=True
    )
    assert ok is True and codec == "h264_nvenc"
    gpu_command = commands[0]
    assert gpu_command[:6] == ["ffmpeg-7.1", "-nostdin", "-y", "-hide_banner", "-loglevel", "error"]
    assert gpu_command[gpu_command.index("-hwaccel") + 1] == "cuda"
    assert gpu_command[gpu_command.index("-c:v") + 1] == "h264_nvenc"
    assert gpu_command[gpu_command.index("-vf") + 1].startswith("scale=1920:1080")
    assert "-pix_fmt" in gpu_command and gpu_command[gpu_command.index("-pix_fmt") + 1] == "yuv420p"
    assert "-movflags" in gpu_command


def test_normalize_clip_never_uses_scale_cuda_proven_broken(tmp_path: Path, monkeypatch):
    """scale_cuda rc=-40 nesta combinação — documentado, proibido voltar."""
    body = MPT_AGENT_SOURCE.split("def _normalize_clip_with_ffmpeg", 1)[1].split(
        "def _preprocess_task_clips", 1
    )[0]
    assert "PROVADO QUEBRADO" in body
    assert "scale_cuda=" not in body
    assert "Parsed_scale_cuda_0" in body  # o erro real fica documentado


def test_normalize_clip_falls_back_to_cpu_without_gpu(tmp_path: Path, monkeypatch):
    commands: list[list[str]] = []
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"mp4")
    temporary = tmp_path / "clip.prep-tmp.mp4"

    class _Done:
        returncode = 0

    def fake_run(command, **_kwargs):
        commands.append(list(command))
        if temporary.name in str(command[-1]) and not temporary.exists():
            temporary.write_bytes(b"preparado")
        return _Done()

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    ok, codec = MPT_AGENT._normalize_clip_with_ffmpeg(
        "ffmpeg-7.1", source, 1920, 1080, gpu=False
    )
    assert ok is True and codec == "libx264"
    cpu_command = commands[0]
    assert "-hwaccel" not in cpu_command
    assert cpu_command[cpu_command.index("-c:v") + 1] == "libx264"
    # O clipe original só é substituído pelo temporário VÁLIDO (replace).
    assert source.read_bytes() == b"preparado"
    assert not temporary.exists()


def test_normalize_clip_keeps_original_when_every_attempt_fails(tmp_path: Path, monkeypatch):
    source = tmp_path / "clip.mp4"
    payload = b"conteudo-original"
    source.write_bytes(payload)

    class _Fail:
        returncode = 1

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", lambda *_a, **_k: _Fail())
    ok, codec = MPT_AGENT._normalize_clip_with_ffmpeg(
        "ffmpeg-7.1", source, 1920, 1080, gpu=True
    )
    assert ok is False and codec == ""
    assert source.read_bytes() == payload
    assert not (tmp_path / "clip.prep-tmp.mp4").exists()


# ---------------------------------------------------------------------------
# Watcher: queda silenciosa de GPU falha rápido (1.0.40 + marcador 1.0.54)
# ---------------------------------------------------------------------------


def test_watcher_markers_include_the_nvenc_failure_line():
    assert MPT_AGENT.MPT_CODEC_FALLBACK_MARKERS == (
        "fallback to libx264",
        "was disabled after a runtime failure",
        "video codec h264_nvenc failed",
    )
    marker_block = MPT_AGENT_SOURCE.split("MPT_CODEC_FALLBACK_MARKERS = (", 1)[1].split(")", 1)[0]
    assert '"video codec h264_nvenc failed"' in marker_block
    # A rede pós-render usa os MESMOS marcadores (nunca versões diferentes).
    post_block = MPT_AGENT_SOURCE.split("if render_nvenc_state == \"ok\":", 1)[1]
    assert "any(marker in engine_log for marker in MPT_CODEC_FALLBACK_MARKERS)" in post_block


def test_fail_fast_message_stays_the_same():
    assert "Falha na GPU: NVENC indisponível" in MPT_AGENT_SOURCE
    assert "Verifique os drivers da NVIDIA" in MPT_AGENT_SOURCE
