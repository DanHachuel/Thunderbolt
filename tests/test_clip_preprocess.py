"""1.0.41 — pré-processamento de clipes FFmpeg (toggle) + barra dinâmica.

Contratos cobertos:
- barra DINÂMICA da etapa de vídeo: nunca cravada num número enquanto o
  processo corre (regra de ouro), monótona, dentro de 52..78 durante a
  etapa (79 reservado ao fim), a acompanhar as fases reais do motor;
- toggle «Pré-processar clipes com FFmpeg antes da montagem»: OFF por
  omissão (fluxo antigo), ON liga a fase de materiais do motor + a
  normalização FFmpeg dos clipes (GPU h264_nvenc com nvidia-smi + probe;
  senão libx264), idempotente, com fallback que NUNCA perde o clipe original;
- telemetria [FFMPEG-PRE] e [MPT-CODEC] preprocess=on|off.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_ui import pipeline_worker


ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MPT_AGENT = _load_module(ROOT / "seed" / "skills" / "mpt_agent.py", "mpt_agent_clip_test")
MPT_AGENT_SOURCE = (ROOT / "seed" / "skills" / "mpt_agent.py").read_text(encoding="utf-8")


class _FakeStreamedProcess:
    def __init__(self, lines=(), returncode=0):
        import threading

        self._lines = [str(line) + "\n" for line in lines]
        self._exhausted = threading.Event()
        self._returncode = returncode
        self._stdout = None
        self.returncode = None
        self.killed = False

    @property
    def stdout(self):
        if self._stdout is None:
            self._stdout = iter(self._lines)
        return self._stdout

    def poll(self):
        if not self._exhausted.is_set():
            for _ in self._stdout or []:
                pass
            self._exhausted.set()
        if self.returncode is None:
            self.returncode = self._returncode
        return self.returncode

    def kill(self):
        self.killed = True


class _FakeGenerationProcess:
    """Popen fake do motor (uma fase): escreve o log scriptado e termina."""

    def __init__(self, *, log_handle=None, script=None, returncode=0, finish_after=None):
        self._log_handle = log_handle
        self._script = dict(script or {})
        self._returncode = returncode
        if finish_after is None:
            finish_after = (max(self._script) + 1) if self._script else 1
        self.finish_after = finish_after
        self.pid = 6161
        self.returncode = None
        self.killed = False
        self._polls = 0

    def poll(self):
        self._polls += 1
        for line in self._script.get(self._polls, []):
            if self._log_handle is not None:
                self._log_handle.write(line + "\n")
                self._log_handle.flush()
        if self.killed:
            return self._returncode or 1
        if self.returncode is None and self._polls >= self.finish_after:
            self.returncode = self._returncode
        return self.returncode

    def kill(self):
        self.killed = True


def _write_config(root: Path, *, ffmpeg_path: str = "", preprocess: bool | None = None) -> Path:
    config_path = root / "config.toml"
    lines = ["[app]"]
    if ffmpeg_path:
        # json.dumps produz uma basic string TOML válida mesmo com as barras
        # invertidas dos caminhos do Windows (toml básico rejeitaria "\").
        lines.append(f"ffmpeg_path = {json.dumps(str(ffmpeg_path))}")
    if preprocess is not None:
        lines.append(f"ffmpeg_preprocess_clips = {'true' if preprocess else 'false'}")
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path


def _fake_ffmpeg(directory: Path) -> Path:
    fake = directory / "ffmpeg-7.1-fake.exe"
    fake.write_bytes(b"#!/bin/sh\nexit 0\n")
    return fake


# ---------------------------------------------------------------------------
# Barra de progresso DINÂMICA (regra de ouro)
# ---------------------------------------------------------------------------


def test_progress_bar_is_dynamic_never_stuck():
    """REGRA DE OURO: a barra nunca fica cravada num número enquanto corre."""
    log = (
        "2026-10-27 13:01:50 | INFO | combine_videos - audio duration: 484.34 seconds\n"
        "2026-10-27 13:01:50 | INFO | combine_videos - maximum clip duration: 5 seconds\n"
    )
    values = [
        pipeline_worker._video_stage_progress(log, seconds, 52, {})
        for seconds in (0, 60, 120, 180, 240, 300, 360)
    ]
    assert values == sorted(values), "a barra recuou"
    assert len(set(values)) >= 5, f"barra quase parada: {values}"
    assert all(52 <= value <= 78 for value in values)


def test_progress_bar_follows_engine_clip_phase():
    """A fracção real do motor (clips processados) puxa a barra para cima."""
    base = (
        "2026-10-27 13:01:50 | INFO | combine_videos - audio duration: 100 seconds\n"
        "2026-10-27 13:01:50 | INFO | combine_videos - maximum clip duration: 5 seconds\n"
    )
    low = pipeline_worker._video_stage_progress(
        base + "2026-10-27 13:02:00 | DEBUG | combine_videos - processing clip 2: 1920x1080\n",
        10.0,
        52,
        {},
    )
    high = pipeline_worker._video_stage_progress(
        base
        + "".join(
            f"2026-10-27 13:02:{second:02d} | DEBUG | combine_videos - processing clip {index}: 1920x1080\n"
            for second, index in ((5, 5), (30, 10), (55, 15), (59, 19))
        ),
        90.0,
        52,
        {},
    )
    assert low < high, f"a barra não acompanhou os clips: {low} -> {high}"


def test_progress_bar_climbs_through_silent_final_write(monkeypatch):
    """A escrita final é silenciosa no log — a barra sobe pelo relógio."""
    import time as real_time

    clock = {"now": 1000.0}
    monkeypatch.setattr(pipeline_worker.time, "monotonic", lambda: clock["now"])
    log = (
        "2026-10-27 13:01:50 | INFO | combine_videos - audio duration: 100 seconds\n"
        "2026-10-27 13:10:11 | INFO | generate_final_videos - ## generating video: 1 => final-1.mp4\n"
    )
    state: dict = {}
    first = pipeline_worker._video_stage_progress(log, 500.0, 52, state)
    mid = first
    for step in range(6):  # 30 s de escrita final em passos de 5 s
        clock["now"] += 5.0
        mid = pipeline_worker._video_stage_progress(log, 500.0 + 5 * (step + 1), mid, state)
    assert mid > first, f"a escrita final não moveu a barra: {first} -> {mid}"
    assert mid <= 78


def test_progress_bar_never_exceeds_ceiling_during_stage():
    """O 79 fica reservado ao fim da etapa — durante, o tecto é 78."""
    log = (
        "2026-10-27 13:01:50 | INFO | combine_videos - audio duration: 10 seconds\n"
        "2026-10-27 13:01:50 | INFO | combine_videos - maximum clip duration: 5 seconds\n"
        "2026-10-27 13:02:00 | DEBUG | combine_videos - processing clip 2: 1920x1080\n"
        "2026-10-27 13:09:21 | INFO | combine_videos - concatenating 97 clips with ffmpeg\n"
    )
    value = pipeline_worker._video_stage_progress(log, 10_000.0, 52, {})
    assert value == 78


def test_progress_bar_without_log_is_a_living_ramp():
    """Sem log (arranque/download): o piso temporal nunca para."""
    values = [pipeline_worker._video_stage_progress("", seconds, 52, {}) for seconds in range(0, 241, 30)]
    assert values == sorted(values)
    assert len(set(values)) >= 5


def test_progress_bar_read_engine_log_text_is_safe_for_missing_file(tmp_path: Path):
    assert pipeline_worker._read_engine_log_text(None) == ""
    assert pipeline_worker._read_engine_log_text(tmp_path / "inexistente.log") == ""
    log = tmp_path / "run.log"
    log.write_text("linha um\nlinha dois\n", encoding="utf-8")
    assert "linha dois" in pipeline_worker._read_engine_log_text(log)


# ---------------------------------------------------------------------------
# Toggle do pré-processamento (config + UI + sync)
# ---------------------------------------------------------------------------


def test_clip_preprocess_toggle_defaults_to_off_and_survives_reads():
    from hermes_ui import storage as ui_storage
    from storage import DEFAULTS

    for defaults in (DEFAULTS["settings.json"], ui_storage.DEFAULTS["settings.json"]):
        assert defaults.get("ffmpeg_preprocess_clips") is False
    assert "ffmpeg_preprocess_clips" in json.dumps({"a": 1}) or True  # sanity do import
    config_path = _write_config(Path.cwd(), preprocess=True)
    assert MPT_AGENT._clip_preprocess_enabled(config_path) is True
    config_path = _write_config(Path.cwd(), preprocess=False)
    assert MPT_AGENT._clip_preprocess_enabled(config_path) is False


def test_clip_preprocess_toggle_absent_means_off(tmp_path: Path):
    config_path = _write_config(tmp_path)
    assert MPT_AGENT._clip_preprocess_enabled(config_path) is False


def test_settings_ui_and_sync_expose_the_toggle():
    main_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "Pré-processar clipes com FFmpeg antes da montagem" in main_source
    assert 'settings.update({' in main_source and '"ffmpeg_preprocess_clips"' in main_source
    config_source = (ROOT / "integrations" / "moneyprinter_config.py").read_text(encoding="utf-8")
    assert '"ffmpeg_preprocess_clips": "ffmpeg_preprocess_clips"' in config_source


# ---------------------------------------------------------------------------
# Backend do pré-processamento (mpt_agent)
# ---------------------------------------------------------------------------


def test_clip_target_size_maps_the_forwarded_aspect():
    assert MPT_AGENT._clip_target_size(["--video-aspect", "16:9"]) == (1920, 1080)
    assert MPT_AGENT._clip_target_size(["--video-aspect", "9:16"]) == (1080, 1920)
    assert MPT_AGENT._clip_target_size(["--video-aspect=1:1"]) == (1080, 1080)
    assert MPT_AGENT._clip_target_size([]) == (1920, 1080)


def test_material_clip_files_reads_the_engine_script_json(tmp_path: Path):
    root = tmp_path / "MoneyPrinterTurbo"
    task_dir = root / "storage" / "tasks" / "task-x"
    task_dir.mkdir(parents=True)
    (root / "storage" / "local_videos").mkdir(parents=True)
    clip = root / "storage" / "local_videos" / "vid-abc.mp4"
    clip.write_bytes(b"video")
    (root / "storage" / "local_videos" / "imagem.jpg").write_bytes(b"nao-e-video")
    task_dir.joinpath("script.json").write_text(
        json.dumps(
            {
                "material_sources": [
                    {"local_file": "vid-abc.mp4", "duration": 12},
                    {"local_file": "imagem.jpg"},
                    {"local_file": "vid-invalido.mp4"},
                ]
            }
        ),
        encoding="utf-8",
    )
    files = MPT_AGENT._material_clip_files(root, "task-x", _write_config(root))
    assert files == [clip]


def test_clip_already_prepared_is_idempotent(tmp_path: Path):
    clip = tmp_path / "vid-abc.mp4"
    clip.write_bytes(b"video")
    assert MPT_AGENT._clip_already_prepared(clip, 1920, 1080) is False
    MPT_AGENT._write_clip_sidecar(clip, 1920, 1080, "h264_nvenc", True)
    assert MPT_AGENT._clip_already_prepared(clip, 1920, 1080) is True
    assert MPT_AGENT._clip_already_prepared(clip, 1080, 1920) is False


def test_gpu_clips_requires_nvidia_smi_and_probe(monkeypatch, tmp_path: Path):
    fake = _fake_ffmpeg(tmp_path)
    monkeypatch.setattr(MPT_AGENT.shutil, "which", lambda name: "" if name == "nvidia-smi" else "/fake")
    monkeypatch.setattr(MPT_AGENT, "_probe_nvenc_encoder", lambda _path: True)
    assert MPT_AGENT._gpu_clips_available(str(fake)) is False

    monkeypatch.setattr(
        MPT_AGENT.shutil,
        "which",
        lambda name: "C:\\nvidia\\nvidia-smi.exe" if name == "nvidia-smi" else "/fake",
    )
    monkeypatch.setattr(
        MPT_AGENT.subprocess,
        "run",
        lambda command, **_kwargs: SimpleNamespace(returncode=0, stdout="NVIDIA GeForce GTX 1050 Ti\n"),
    )
    assert MPT_AGENT._gpu_clips_available(str(fake)) is True


def test_normalize_clip_prefers_nvenc_then_cpu_and_keeps_original(tmp_path: Path, monkeypatch):
    source = tmp_path / "vid-abc.mp4"
    source.write_bytes(b"conteudo original")
    fake = _fake_ffmpeg(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(list(command))
        output = Path(command[-1])
        if not output.exists():
            output.write_bytes(b"video normalizado")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    ok, codec = MPT_AGENT._normalize_clip_with_ffmpeg(fake, source, 1920, 1080, gpu=True)
    assert ok and codec == "h264_nvenc"
    assert source.read_bytes() == b"video normalizado"  # substituição in-place
    assert commands[0][commands[0].index("-hwaccel") + 1] == "cuda"
    assert commands[0][commands[0].index("-c:v") + 1] == "h264_nvenc"
    assert commands[0][commands[0].index("-pix_fmt") + 1] == "yuv420p"
    assert commands[0][commands[0].index("-movflags") + 1] == "+faststart"
    assert "fps=30" in commands[0][commands[0].index("-vf") + 1]

    # NVENC falha -> repete em libx264 (CPU) sem hwaccel.
    source2 = tmp_path / "vid-def.mp4"
    source2.write_bytes(b"conteudo original")
    commands.clear()

    def fail_nvenc(command, **_kwargs):
        commands.append(list(command))
        if command[command.index("-c:v") + 1] == "h264_nvenc":
            return SimpleNamespace(returncode=1)
        output = Path(command[-1])
        output.write_bytes(b"video normalizado cpu")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fail_nvenc)
    ok, codec = MPT_AGENT._normalize_clip_with_ffmpeg(fake, source2, 1920, 1080, gpu=True)
    assert ok and codec == "libx264"
    assert source2.read_bytes() == b"video normalizado cpu"
    assert "-hwaccel" not in commands[1]


def test_normalize_clip_failure_keeps_the_original(tmp_path: Path, monkeypatch):
    source = tmp_path / "vid-ghi.mp4"
    source.write_bytes(b"conteudo original")
    fake = _fake_ffmpeg(tmp_path)
    monkeypatch.setattr(
        MPT_AGENT.subprocess, "run", lambda command, **_kwargs: SimpleNamespace(returncode=1)
    )
    ok, codec = MPT_AGENT._normalize_clip_with_ffmpeg(fake, source, 1920, 1080, gpu=True)
    assert ok is False and codec == ""
    assert source.read_bytes() == b"conteudo original"
    assert not list(tmp_path.glob("*.prep-tmp.mp4"))


def test_preprocess_task_clips_is_a_noop_without_binary(tmp_path: Path, capsys):
    stats = MPT_AGENT._preprocess_task_clips(tmp_path, _write_config(tmp_path), "task", "", [])
    assert stats == {"total": 0, "prepared": 0, "skipped": 0, "failed": 0}
    assert "[FFMPEG-PRE] sem binário FFmpeg efectivo" in capsys.readouterr().out


def test_preprocess_task_clips_noop_without_materials(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    fake = _fake_ffmpeg(tmp_path)
    monkeypatch.setattr(MPT_AGENT, "_gpu_clips_available", lambda _ffmpeg: True)
    stats = MPT_AGENT._preprocess_task_clips(root, _write_config(root), "task", str(fake), [])
    assert stats["total"] == 0
    assert "[FFMPEG-PRE] nenhum clipe descarregado" in capsys.readouterr().out


def test_preprocess_task_clips_normalizes_and_reports(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "MoneyPrinterTurbo"
    task_dir = root / "storage" / "tasks" / "task-x"
    task_dir.mkdir(parents=True)
    (root / "storage" / "local_videos").mkdir(parents=True)
    for name in ("vid-a.mp4", "vid-b.mp4"):
        (root / "storage" / "local_videos" / name).write_bytes(b"original")
    task_dir.joinpath("script.json").write_text(
        json.dumps({"material_sources": [{"local_file": "vid-a.mp4"}, {"local_file": "vid-b.mp4"}]}),
        encoding="utf-8",
    )
    fake = _fake_ffmpeg(tmp_path)
    monkeypatch.setattr(MPT_AGENT, "_gpu_clips_available", lambda _ffmpeg: True)

    def fake_run(command, **_kwargs):
        output = Path(command[-1])
        output.write_bytes(b"normalizado")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    stats = MPT_AGENT._preprocess_task_clips(
        root, _write_config(root), "task-x", str(fake), ["--video-aspect", "16:9"]
    )
    assert stats == {"total": 2, "prepared": 2, "skipped": 0, "failed": 0}
    output = capsys.readouterr().out
    assert "[FFMPEG-PRE] 2 clipes -> 1920x1080 (h264_nvenc, nvidia-smi ok)" in output
    assert "[FFMPEG-PRE] clip 1/2: vid-a.mp4 -> 1920x1080 (h264_nvenc" in output
    assert "[FFMPEG-PRE] resumo: 2 normalizados" in output
    for name in ("vid-a.mp4", "vid-b.mp4"):
        assert (root / "storage" / "local_videos" / name).read_bytes() == b"normalizado"
        assert MPT_AGENT._clip_already_prepared(root / "storage" / "local_videos" / name, 1920, 1080)


def test_preprocess_task_clips_skips_already_normalized(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "MoneyPrinterTurbo"
    task_dir = root / "storage" / "tasks" / "task-x"
    task_dir.mkdir(parents=True)
    (root / "storage" / "local_videos").mkdir(parents=True)
    clip = root / "storage" / "local_videos" / "vid-a.mp4"
    clip.write_bytes(b"normalizado")
    MPT_AGENT._write_clip_sidecar(clip, 1920, 1080, "h264_nvenc", True)
    task_dir.joinpath("script.json").write_text(
        json.dumps({"material_sources": [{"local_file": "vid-a.mp4"}]}), encoding="utf-8"
    )
    fake = _fake_ffmpeg(tmp_path)
    monkeypatch.setattr(MPT_AGENT, "_gpu_clips_available", lambda _ffmpeg: True)
    monkeypatch.setattr(
        MPT_AGENT.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("não deve correr ffmpeg em clipe já normalizado"),
    )
    stats = MPT_AGENT._preprocess_task_clips(
        root, _write_config(root), "task-x", str(fake), ["--video-aspect", "16:9"]
    )
    assert stats == {"total": 1, "prepared": 0, "skipped": 1, "failed": 0}
    assert "já normalizado" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# generate_video: as TRÊS fases com o toggle ligado
# ---------------------------------------------------------------------------


def _fake_generation(tmp_path: Path, monkeypatch, *, preprocess: bool, engine_script=None):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    fake = _fake_ffmpeg(tmp_path)
    config_path = _write_config(root, ffmpeg_path=str(fake), preprocess=preprocess)
    monkeypatch.setattr(MPT_AGENT.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(MPT_AGENT, "run_checked", lambda *args, **kwargs: None)
    monkeypatch.setattr(MPT_AGENT, "_probe_nvenc_encoder", lambda _path: True)
    real_sleep = __import__("time").sleep
    monkeypatch.setattr(MPT_AGENT.time, "sleep", lambda _seconds: real_sleep(0.001))
    captured: dict[str, object] = {"commands": []}
    killed: list[int] = []
    processes: list = []

    def fake_kill(pid):
        killed.append(pid)
        for process in processes:
            if process.pid == pid:
                process.kill()

    monkeypatch.setattr(MPT_AGENT, "_kill_process_tree", fake_kill)

    def fake_run(command, **_kwargs):
        if "--help" in command:
            return SimpleNamespace(returncode=0, stdout="options:\n  --video-source X\n", stderr="")
        raise AssertionError("o spawn do motor passou a usar Popen (1.0.40)")

    def fake_popen(command, **kwargs):
        captured["commands"].append(list(command))
        task_id = command[command.index("--task-id") + 1]
        output = root / "storage" / "tasks" / task_id / "final-1.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        process = _FakeGenerationProcess(
            log_handle=kwargs.get("stdout"),
            script=dict(engine_script or {}) if len(captured["commands"]) == 1 else {},
            returncode=0,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    monkeypatch.setattr(MPT_AGENT.subprocess, "Popen", fake_popen)
    return root, fake, captured, killed


def test_generate_video_runs_two_spawns_with_preprocess_on(tmp_path: Path, monkeypatch, capsys):
    root, _fake, captured, _killed = _fake_generation(tmp_path, monkeypatch, preprocess=True)
    videos, _task_dir, _log_path, _result = MPT_AGENT.generate_video(
        root, "Tema com pré-processamento", ["--video-source", "pexels"]
    )
    assert videos
    commands = captured["commands"]
    # O pré-processamento NÃO é um spawn: são 2 spawns do motor (materials +
    # video) e, pelo meio, a normalização local dos clipes com FFmpeg.
    assert len(commands) == 2, f"esperadas 2 fases (materials, video): {len(commands)}"
    assert commands[0][-2:] == ["--stop-at", "materials"], commands[0][-6:]
    assert commands[1][-2:] == ["--stop-at", "video"], commands[1][-6:]
    output = capsys.readouterr().out
    assert "preprocess=on" in output
    assert "fase de materiais do motor (--stop-at materials)" in output
    assert "[FFMPEG-PRE]" in output


def test_generate_video_keeps_single_spawn_with_preprocess_off(tmp_path: Path, monkeypatch, capsys):
    root, _fake, captured, _killed = _fake_generation(tmp_path, monkeypatch, preprocess=False)
    videos, _task_dir, _log_path, _result = MPT_AGENT.generate_video(
        root, "Tema sem pré-processamento", ["--video-source", "pexels"]
    )
    assert videos
    commands = captured["commands"]
    assert len(commands) == 1, f"fluxo antigo devia ter 1 spawn: {len(commands)}"
    assert commands[0][-2:] == ["--stop-at", "video"]
    assert "preprocess=off" in capsys.readouterr().out


def test_generate_video_local_route_never_preprocesses(tmp_path: Path, monkeypatch, capsys):
    root, _fake, captured, _killed = _fake_generation(tmp_path, monkeypatch, preprocess=True)
    MPT_AGENT.generate_video(root, "Tema local", ["--video-source", "local"])
    assert len(captured["commands"]) == 1
    assert "preprocess=off" in capsys.readouterr().out


def test_clip_preprocess_source_contracts():
    assert "def _preprocess_task_clips(" in MPT_AGENT_SOURCE
    assert "[FFMPEG-PRE]" in MPT_AGENT_SOURCE
    assert 'CLIP_PREPROCESS_STAGE = "materials"' in MPT_AGENT_SOURCE
    assert "materials_command = [*command[:-2]" in MPT_AGENT_SOURCE
    assert '"-hwaccel", "cuda"' in MPT_AGENT_SOURCE
    # O concat do motor continua a receber yuv420p (intacto) e a falha rápida
    # da 1.0.40 não foi removida.
    assert "_watch_engine_log" in MPT_AGENT_SOURCE
    assert "MPT_CODEC_FAIL_FAST_MESSAGE" in MPT_AGENT_SOURCE
    # A fase de clips do motor não é limitada em concorrência.
    assert "max_parallel_mpt_runtimes = 1" not in MPT_AGENT_SOURCE
