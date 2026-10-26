"""1.0.36 — Aceleração de hardware (NVENC) restaurada sem quebrar o player.

Contratos desta release:
- o binário FFmpeg escolhido no painel é injectado no ambiente do motor MPT
  (IMAGEIO_FFMPEG_EXE + FFMPEG_BINARY) — o fork ignora o ffmpeg_path do
  config.toml e usava o que encontrasse no PATH/wheel;
- o codec é decidido por probe REAL (encode de 1 s — o "-encoders" anuncia
  h264_nvenc mesmo quando o encoder falha a abrir, error -40 da 1.0.23);
  GPU indisponível descarrega para libx264 ANTES do render;
- o banner [MPT-CODEC] imprime-se exactamente antes de o motor arrancar;
- os marcadores de fallback do próprio motor denunciam uma descida de GPU
  a meio do render;
- as escritas locais do MoviePy (montagem + queima de legendas da rota
  Pexels/Pixabay, a etapa que custava ~45 min na CPU) usam h264_nvenc com
  retry único em libx264 e SEM perder os WEB_SAFE_MP4_FFMPEG_PARAMS da
  1.0.29 (+faststart +yuv420p) — o vídeo continua streamable no browser.
"""

from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_ui import text_to_images


ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MPT_AGENT = _load_module(ROOT / "seed" / "skills" / "mpt_agent.py", "mpt_agent_nvenc_test")
MPT_AGENT_SOURCE = (ROOT / "seed" / "skills" / "mpt_agent.py").read_text(encoding="utf-8")
TEXT_TO_IMAGES_SOURCE = (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")


class _FakeStreamedProcess:
    """Fake process para _run_streamed: termina depois do stdout drenado."""

    def __init__(self, lines, returncode=0):
        self._lines = [str(line) + "\n" for line in lines]
        self._exhausted = threading.Event()
        self._returncode = returncode
        self._stdout = None
        self.returncode = None
        self.killed = False

    def _iter_stdout(self):
        for line in self._lines:
            yield line
        self._exhausted.set()

    @property
    def stdout(self):
        if self._stdout is None:
            self._stdout = self._iter_stdout()
        return self._stdout

    def poll(self):
        if not self._exhausted.is_set():
            return None
        if self.returncode is None:
            self.returncode = self._returncode
        return self.returncode

    def kill(self):
        self.killed = True
        if self.returncode is None:
            self.returncode = -9
        self._exhausted.set()


def _write_config(root: Path, *, ffmpeg_path: str = "", video_codec: str = "") -> Path:
    import json as _json

    config_path = root / "config.toml"
    lines = ["[app]"]
    if ffmpeg_path:
        # json.dumps produz uma basic string TOML válida mesmo com as barras
        # invertidas dos caminhos do Windows.
        lines.append(f"ffmpeg_path = {_json.dumps(str(ffmpeg_path))}")
    if video_codec:
        lines.append(f"video_codec = {_json.dumps(str(video_codec))}")
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path


def _fake_ffmpeg(directory: Path) -> Path:
    fake = directory / "ffmpeg-7.1-fake.exe"
    fake.write_bytes(b"#!/bin/sh\nexit 0\n")
    return fake


# ---------------------------------------------------------------------------
# mpt_agent — injecção de ambiente
# ---------------------------------------------------------------------------


def test_ffmpeg_environment_injects_both_keys_from_config(tmp_path: Path, monkeypatch):
    fake = _fake_ffmpeg(tmp_path)
    config_path = _write_config(tmp_path, ffmpeg_path=str(fake))
    monkeypatch.setenv("THUNDERBOLT_ENV_MARKER", "herdado-do-worker")
    environment = MPT_AGENT._ffmpeg_environment(config_path)
    # 1.0.37: a injecção EXTENDE o ambiente herdado, nunca o substitui —
    # o WinError 10106 provou o custo de o motor arrancar sem SYSTEMROOT.
    assert environment["IMAGEIO_FFMPEG_EXE"] == str(fake)
    assert environment["FFMPEG_BINARY"] == str(fake)
    assert environment["THUNDERBOLT_ENV_MARKER"] == "herdado-do-worker"
    assert environment.get("SYSTEMROOT", os.environ.get("SYSTEMROOT", "C:\\Windows"))


def test_ffmpeg_environment_extends_a_copy_of_os_environ(tmp_path: Path, monkeypatch):
    fake = _fake_ffmpeg(tmp_path)
    config_path = _write_config(tmp_path, ffmpeg_path=str(fake))
    monkeypatch.setenv("THUNDERBOLT_ENV_MARKER_2", "presente-na-copia")
    environment = MPT_AGENT._ffmpeg_environment(config_path)
    assert isinstance(environment, dict)
    for key, value in os.environ.items():
        if key in {"IMAGEIO_FFMPEG_EXE", "FFMPEG_BINARY"}:
            continue
        assert environment.get(key) == value, f"o ambiente perdeu {key}"
    assert environment["THUNDERBOLT_ENV_MARKER_2"] == "presente-na-copia"


def test_windows_essentials_are_reinjected_with_fallback_when_missing(monkeypatch):
    monkeypatch.setattr(MPT_AGENT.os, "name", "nt")
    for key in MPT_AGENT.WINDOWS_ESSENTIAL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    environment: dict[str, str] = {}
    MPT_AGENT._ensure_windows_essentials(environment)
    assert environment["SYSTEMROOT"] == "C:\\Windows"
    assert environment["WINDIR"] == "C:\\Windows"
    # Chaves sem fallback sano nunca são inventadas — apenas preservadas da
    # cópia base (allowlist anti-remoção, não fabricação de valores).
    assert "COMSPEC" not in environment
    assert "APPDATA" not in environment
    assert "LOCALAPPDATA" not in environment


def test_windows_essentials_keep_existing_values(monkeypatch):
    monkeypatch.setattr(MPT_AGENT.os, "name", "nt")
    monkeypatch.setenv("SYSTEMROOT", "D:\\WinCustom")
    environment: dict[str, str] = {"SYSTEMROOT": "D:\\WinCustom"}
    MPT_AGENT._ensure_windows_essentials(environment)
    assert environment["SYSTEMROOT"] == "D:\\WinCustom"


def test_windows_essentials_are_a_noop_outside_windows(monkeypatch):
    monkeypatch.setattr(MPT_AGENT.os, "name", "posix")
    environment: dict[str, str] = {}
    MPT_AGENT._ensure_windows_essentials(environment)
    assert environment == {}


def test_ffmpeg_environment_is_none_without_a_real_binary(tmp_path: Path):
    # Caminho vazio, inexistente e "ffmpeg" nu do PATH: nada se injecta —
    # o motor herda o ambiente exactamente como na v1.0.01.
    empty = MPT_AGENT._ffmpeg_environment(_write_config(tmp_path))
    missing = MPT_AGENT._ffmpeg_environment(
        _write_config(tmp_path, ffmpeg_path=str(tmp_path / "ffmpeg.exe"))
    )
    assert empty is None
    assert missing is None


def test_probe_nvenc_encoder_runs_a_real_encode_and_caches(tmp_path: Path, monkeypatch):
    fake = _fake_ffmpeg(tmp_path)
    MPT_AGENT._NVENC_PROBE_CACHE.clear()
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(list(command))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    assert MPT_AGENT._probe_nvenc_encoder(str(fake)) is True
    assert MPT_AGENT._probe_nvenc_encoder(str(fake)) is True
    assert len(commands) == 1  # cache por binário: o probe não se repete
    probe = commands[0]
    assert probe[0] == str(fake)
    # Probe REAL: encode h264_nvenc de facto — nunca o "-encoders" que mente.
    assert probe[probe.index("-c:v") + 1] == "h264_nvenc"
    assert probe[probe.index("-pix_fmt") + 1] == "yuv420p"
    assert "-encoders" not in probe


def test_probe_nvenc_encoder_reports_unavailable_on_failure(tmp_path: Path, monkeypatch):
    fake = _fake_ffmpeg(tmp_path)
    MPT_AGENT._NVENC_PROBE_CACHE.clear()

    def failing_run(command, **_kwargs):
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", failing_run)
    assert MPT_AGENT._probe_nvenc_encoder(str(fake)) is False

    def exploding_run(command, **_kwargs):
        raise MPT_AGENT.subprocess.TimeoutExpired(cmd=command, timeout=45)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", exploding_run)
    assert MPT_AGENT._probe_nvenc_encoder(str(fake)) is False


# ---------------------------------------------------------------------------
# mpt_agent — decisão de codec (probe → config.toml)
# ---------------------------------------------------------------------------


def test_resolve_render_codec_forces_nvenc_when_probe_passes(tmp_path: Path, monkeypatch):
    fake = _fake_ffmpeg(tmp_path)
    config_path = _write_config(tmp_path, ffmpeg_path=str(fake), video_codec="libx264")
    monkeypatch.setattr(MPT_AGENT, "_probe_nvenc_encoder", lambda _path: True)
    codec, state = MPT_AGENT._resolve_render_codec(config_path, str(fake))
    assert (codec, state) == ("h264_nvenc", "ok")
    assert 'video_codec = "h264_nvenc"' in config_path.read_text(encoding="utf-8")


def test_resolve_render_codec_downgrades_to_cpu_before_render(tmp_path: Path, monkeypatch):
    fake = _fake_ffmpeg(tmp_path)
    config_path = _write_config(tmp_path, ffmpeg_path=str(fake), video_codec="h264_nvenc")
    monkeypatch.setattr(MPT_AGENT, "_probe_nvenc_encoder", lambda _path: False)
    codec, state = MPT_AGENT._resolve_render_codec(config_path, str(fake))
    assert (codec, state) == ("libx264", "unavailable")
    # O config fica coerente: o motor não perde tempo a tentar NVENC sabendo
    # que o encoder falha — o fallback de runtime do MPT é a segunda rede.
    assert 'video_codec = "libx264"' in config_path.read_text(encoding="utf-8")


def test_resolve_render_codec_without_binary_never_touches_config(tmp_path: Path):
    config_path = _write_config(tmp_path, video_codec="h264_nvenc")
    before = config_path.read_text(encoding="utf-8")
    codec, state = MPT_AGENT._resolve_render_codec(config_path, "")
    assert codec == "h264_nvenc"
    assert state == "unknown"
    assert config_path.read_text(encoding="utf-8") == before


def test_resolve_render_codec_survives_readonly_config(tmp_path: Path, monkeypatch):
    fake = _fake_ffmpeg(tmp_path)
    config_path = _write_config(tmp_path, ffmpeg_path=str(fake), video_codec="h264_nvenc")

    def refuse_write(_path, _text):
        raise PermissionError("read-only install")

    monkeypatch.setattr(MPT_AGENT, "_atomic_write_text", refuse_write)
    monkeypatch.setattr(MPT_AGENT, "_probe_nvenc_encoder", lambda _path: False)
    # Config não gravável nunca mata o render: segue com o codec presente.
    assert MPT_AGENT._resolve_render_codec(config_path, str(fake)) == ("libx264", "unavailable")


# ---------------------------------------------------------------------------
# mpt_agent — banner [MPT-CODEC] + env no spawn do render
# ---------------------------------------------------------------------------


def _fake_generation_environment(tmp_path: Path, monkeypatch, *, engine_log_marker: str = ""):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    fake_ffmpeg = _fake_ffmpeg(tmp_path)
    config_path = _write_config(
        tmp_path, ffmpeg_path=str(fake_ffmpeg), video_codec="h264_nvenc"
    )
    # O config do MPT vive dentro do root do projecto.
    (root / "config.toml").write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(MPT_AGENT.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(MPT_AGENT, "run_checked", lambda *args, **kwargs: None)
    monkeypatch.setattr(MPT_AGENT, "_probe_nvenc_encoder", lambda _path: True)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        if "--help" in command:
            return SimpleNamespace(
                returncode=0,
                stdout="options:\n  --video-source VIDEO_SOURCE\n  --video-script VIDEO_SOURCE\n",
                stderr="",
            )
        captured["command"] = command
        captured["kwargs"] = kwargs
        stdout = kwargs.get("stdout")
        if engine_log_marker and stdout is not None:
            stdout.write(engine_log_marker)
        task_id = command[command.index("--task-id") + 1]
        output = root / "storage" / "tasks" / task_id / "final-1.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    return root, str(fake_ffmpeg), captured


def test_generate_video_prints_codec_banner_and_injects_environment(
    tmp_path: Path, monkeypatch, capsys
):
    root, fake_ffmpeg, captured = _fake_generation_environment(tmp_path, monkeypatch)
    videos, _task_dir, _log_path, _result_path = MPT_AGENT.generate_video(
        root, "Tema com GPU", ["--video-source", "pexels"]
    )
    assert videos
    output = capsys.readouterr().out
    banner = next(line for line in output.splitlines() if line.startswith("[MPT-CODEC]"))
    assert f"ffmpeg={fake_ffmpeg}" in banner
    assert "codec=h264_nvenc" in banner
    assert "nvenc=ok" in banner
    # O banner é a última linha antes de o motor arrancar.
    assert output.index("[MPT-CODEC]") < output.index("starting video generation, task ID:")
    kwargs = captured["kwargs"]
    assert kwargs["env"]["IMAGEIO_FFMPEG_EXE"] == fake_ffmpeg
    assert kwargs["env"]["FFMPEG_BINARY"] == fake_ffmpeg
    # 1.0.37: o env do motor é EXTENSÃO do ambiente herdado — o
    # WinError 10106 nasceu de o env ter ficado reduzido às 2 chaves.
    assert "SYSTEMROOT" in kwargs["env"]
    assert "PATH" in kwargs["env"]


def test_generate_video_reports_engine_fallback_marker(tmp_path: Path, monkeypatch, capsys):
    root, _fake_ffmpeg, _captured = _fake_generation_environment(
        tmp_path,
        monkeypatch,
        engine_log_marker="video codec h264_nvenc failed, fallback to libx264. reason: boom\n",
    )
    videos, _task_dir, _log_path, _result_path = MPT_AGENT.generate_video(
        root, "Tema com queda de GPU", ["--video-source", "pexels"]
    )
    assert videos
    output = capsys.readouterr().out
    assert "[MPT-CODEC] [AVISO] o motor caiu para libx264 (CPU) durante o render" in output


def test_generate_video_without_configured_ffmpeg_keeps_inherited_environment(
    tmp_path: Path, monkeypatch, capsys
):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    monkeypatch.setattr(MPT_AGENT.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(MPT_AGENT, "run_checked", lambda *args, **kwargs: None)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        if "--help" in command:
            return SimpleNamespace(returncode=0, stdout="options:\n  --video-source VIDEO_SOURCE\n", stderr="")
        captured["kwargs"] = kwargs
        task_id = command[command.index("--task-id") + 1]
        output = root / "storage" / "tasks" / task_id / "final-1.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    MPT_AGENT.generate_video(root, "Tema sem ffmpeg no config", ["--video-source", "pexels"])
    kwargs = captured["kwargs"]
    assert kwargs["env"] is None
    banner = next(
        line for line in capsys.readouterr().out.splitlines() if line.startswith("[MPT-CODEC]")
    )
    assert "nvenc=unknown" in banner


# ---------------------------------------------------------------------------
# mpt_agent — via Azure segmentada usa o mesmo binário efectivo
# ---------------------------------------------------------------------------


def test_azure_chunked_environment_carries_ffmpeg_binary(tmp_path: Path, monkeypatch):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    fake_ffmpeg = _fake_ffmpeg(tmp_path)
    config_path = _write_config(tmp_path, ffmpeg_path=str(fake_ffmpeg))
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n[azure]\nspeech_key = \"key\"\nspeech_region = \"eastus\"\n",
        encoding="utf-8",
    )
    task_dir = root / "storage" / "tasks" / "task-azure"
    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        captured["kwargs"] = kwargs
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"audio")
        return _FakeStreamedProcess(["AZURE_CHUNK_COUNT=2"], returncode=0)

    monkeypatch.setattr(MPT_AGENT.subprocess, "Popen", fake_popen)
    audio = MPT_AGENT._prepare_azure_v2_chunked_audio(
        root,
        config_path,
        task_dir,
        ["--voice-name", "en-US-JennyNeural-V2-Female", "--video-script", "Roteiro"],
        "/usr/bin/uv",
    )
    assert audio is not None
    environment = captured["kwargs"]["env"]
    assert environment["IMAGEIO_FFMPEG_EXE"] == str(fake_ffmpeg)
    assert environment["FFMPEG_BINARY"] == str(fake_ffmpeg)


# ---------------------------------------------------------------------------
# text_to_images — escritas locais com GPU + fallback + web-safe intactos
# ---------------------------------------------------------------------------


class _FakeClip:
    def __init__(self, fail_codecs=()):
        self.calls: list[dict] = []
        self._fail_codecs = set(fail_codecs)

    def write_videofile(self, path, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if kwargs.get("codec") in self._fail_codecs:
            raise RuntimeError("encoder exploded")


def test_write_web_safe_videofile_uses_nvenc_when_probe_passes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(text_to_images, "_nvenc_encoder_available", lambda _ffmpeg: True)
    clip = _FakeClip()
    codec = text_to_images._write_web_safe_videofile(clip, tmp_path / "out.mp4", fps=30)
    assert codec == "h264_nvenc"
    assert len(clip.calls) == 1
    call = clip.calls[0]
    assert call["codec"] == "h264_nvenc"
    assert call["ffmpeg_params"] == text_to_images.WEB_SAFE_MP4_FFMPEG_PARAMS
    assert call["logger"] is None


def test_write_web_safe_videofile_retries_once_on_cpu_when_nvenc_fails(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.setattr(text_to_images, "_nvenc_encoder_available", lambda _ffmpeg: True)
    clip = _FakeClip(fail_codecs={"h264_nvenc"})
    codec = text_to_images._write_web_safe_videofile(clip, tmp_path / "out.mp4", fps=30)
    assert codec == "libx264"
    assert [call["codec"] for call in clip.calls] == ["h264_nvenc", "libx264"]
    # A compatibilidade web da 1.0.29 viaja em AMBAS as tentativas.
    for call in clip.calls:
        assert call["ffmpeg_params"] == text_to_images.WEB_SAFE_MP4_FFMPEG_PARAMS
    assert "NVENC falhou na escrita" in capsys.readouterr().err


def test_write_web_safe_videofile_is_pure_cpu_when_probe_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(text_to_images, "_nvenc_encoder_available", lambda _ffmpeg: False)
    clip = _FakeClip()
    codec = text_to_images._write_web_safe_videofile(clip, tmp_path / "out.mp4", fps=30)
    assert codec == "libx264"
    assert len(clip.calls) == 1
    assert clip.calls[0]["codec"] == "libx264"
    assert clip.calls[0]["ffmpeg_params"] == text_to_images.WEB_SAFE_MP4_FFMPEG_PARAMS


def test_moviepy_ffmpeg_binary_mirrors_moviepy_resolution(monkeypatch):
    monkeypatch.setenv("FFMPEG_BINARY", "C:\\ffmpeg\\explicit-ffmpeg.exe")
    assert text_to_images._moviepy_ffmpeg_binary() == "C:\\ffmpeg\\explicit-ffmpeg.exe"
    monkeypatch.delenv("FFMPEG_BINARY")
    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", "C:\\ffmpeg\\imageio-ffmpeg.exe")
    assert text_to_images._moviepy_ffmpeg_binary() == "C:\\ffmpeg\\imageio-ffmpeg.exe"


def test_nvenc_probe_is_cached_per_binary_and_mtime(tmp_path: Path, monkeypatch):
    fake = _fake_ffmpeg(tmp_path)
    text_to_images._NVENC_PROBE_CACHE.clear()
    calls: list[list[str]] = []
    import subprocess as real_subprocess

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(real_subprocess, "run", fake_run)
    assert text_to_images._nvenc_encoder_available(str(fake)) is True
    assert text_to_images._nvenc_encoder_available(str(fake)) is True
    assert len(calls) == 1
    assert calls[0][calls[0].index("-c:v") + 1] == "h264_nvenc"
    assert "-encoders" not in calls[0]


# ---------------------------------------------------------------------------
# Contratos de source — a camada 1.0.29/1.0.32/1.0.35 continua intocada
# ---------------------------------------------------------------------------


def test_mpt_agent_contracts_of_the_codec_restoration():
    # O spawn do render recebe o ambiente injectado…
    assert "env=render_environment," in MPT_AGENT_SOURCE
    # …o banner sai antes de o motor arrancar…
    assert MPT_AGENT_SOURCE.index("f\"[MPT-CODEC] ffmpeg=") < MPT_AGENT_SOURCE.index(
        "starting video generation, task ID:"
    )
    # …o probe é um encode REAL (nunca o "-encoders" que anuncia encoders
    # que depois falham a abrir — error -40 da 1.0.23)…
    probe_body = MPT_AGENT_SOURCE.split("def _probe_nvenc_encoder", 1)[1].split(
        "def _resolve_render_codec", 1
    )[0]
    assert '"-encoders"' not in probe_body
    assert '"-c:v"' in probe_body and '"-pix_fmt"' in probe_body
    # …e a via Azure segmentada injecta o MESMO binário nas duas chaves.
    assert 'environment["FFMPEG_BINARY"] = ffmpeg_path' in MPT_AGENT_SOURCE


def test_mpt_agent_environment_is_extension_not_replacement():
    # 1.0.37 — contrato anti-WinError 10106: a injecção de FFmpeg parte
    # SEMPRE de uma cópia completa do ambiente herdado (PATH, SYSTEMROOT,
    # TEMP…); o dict mínimo de 2 chaves da 1.0.36 matava o Winsock
    # (mswsock.dll não carregava) e a primeira rede do motor rebentava.
    env_helper_body = MPT_AGENT_SOURCE.split("def _ffmpeg_environment", 1)[1].split(
        "def _probe_nvenc_encoder", 1
    )[0]
    assert "environment = os.environ.copy()" in env_helper_body
    assert "_ensure_windows_essentials(environment)" in env_helper_body
    assert 'return {"IMAGEIO_FFMPEG_EXE"' not in MPT_AGENT_SOURCE
    # A allowlist cobre as variáveis que o runtime do Windows exige.
    assert '"SYSTEMROOT", "WINDIR", "COMSPEC", "APPDATA", "LOCALAPPDATA"' in MPT_AGENT_SOURCE
    assert '"SYSTEMROOT": "C:\\\\Windows"' in MPT_AGENT_SOURCE


def test_local_writes_keep_web_safe_params_and_use_the_gpu_writer():
    # As duas escritas locais (montagem text_to_images + queima de legendas
    # da rota Pexels/Pixabay) delegam no helper com GPU + fallback…
    assert TEXT_TO_IMAGES_SOURCE.count("_write_web_safe_videofile(") == 3  # def + 2 chamadas
    # …e o helper mantém os parâmetros web-safe da 1.0.29 em ambas as
    # tentativas (GPU e CPU) — o player do navegador continua a tocar.
    assert TEXT_TO_IMAGES_SOURCE.count("ffmpeg_params=WEB_SAFE_MP4_FFMPEG_PARAMS") == 2
    # A telemetria da queima reporta o codec efectivo.
    assert "(codec={burn_codec})" in TEXT_TO_IMAGES_SOURCE


def test_streamable_normalizer_and_player_layers_stay_untouched():
    # A camada de normalização 1.0.29 do worker não ganha NVENC (o re-encode
    # raro de pix_fmt inválido continua em CPU — contrato test_streamable_video)
    # e os parâmetros web-safe seguem definidos com o valor exacto da 1.0.29.
    worker_source = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
    reencode_block = worker_source.split("def _streamable_fix_command", 1)[1].split("return command", 1)[0]
    assert '"-c:v", "libx264"' in reencode_block
    assert "h264_nvenc" not in reencode_block
    assert 'WEB_SAFE_MP4_FFMPEG_PARAMS = ["-movflags", "+faststart", "-pix_fmt", "yuv420p"]' in (
        TEXT_TO_IMAGES_SOURCE
    )
    # O player 1.0.35 (URL /tb-media/ com fallback de caminho) e o contrato
    # do codec no sync do config.toml continuam como estavam.
    app_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "_tb_media_video_url" in app_source
    config_source = (ROOT / "integrations" / "moneyprinter_config.py").read_text(encoding="utf-8")
    assert 'NVENC_VIDEO_CODEC = "h264_nvenc"' in config_source
    assert 'app["video_codec"] = NVENC_VIDEO_CODEC' in config_source
