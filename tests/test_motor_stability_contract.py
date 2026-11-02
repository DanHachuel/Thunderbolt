"""1.0.51 — CONTRATO DE ESTABILIDADE DO MOTOR («Motor Lock» do CI).

O utilizador está exausto de features novas quebrarem o motor. Este ficheiro
é o guarda-costas: se alguém refactorar a geração de vídeo e quebrar uma das
defesas do WinError 32 (temp_audiofile único, travão do fallback falso,
TEMP isolado no spawn, limpeza de órfãos), o CI barra aqui.

Contratos cobertos (a tarefa DEVE falhar se qualquer um regredir):
- o patch de runtime do motor (``seed/skills/mpt_runtime_patch.py``) injecta
  um ``temp_audiofile`` com nome ÚNICO por execução (uuid4) no write do
  MoviePy — nunca o nome estático ``TEMP_MPY_wvf_snd`` do motor;
- a lógica de codec NUNCA desativa o NVENC por WinError 32 — bloqueio de
  ficheiro repete (nome fresco) e só uma falha REAL de encoder cai para
  ``libx264`` como o motor manda (o fail-fast do Thunderbolt fica intacto);
- o env do Popen do motor inclui SEMPRE o TEMP isolado do Thunderbolt
  (mpt_agent e pipeline_worker — camada da 1.0.43 intacta);
- temporários ``*TEMP_MPY_*`` órfãos com mais de 24 h são apagados antes do
  render;
- o spawn do motor carrega o patch antes de executar o cli.py (bootstrap).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MPT_AGENT_PATH = ROOT / "seed" / "skills" / "mpt_agent.py"
PATCH_PATH = ROOT / "seed" / "skills" / "mpt_runtime_patch.py"

MPT_AGENT = _load_module(MPT_AGENT_PATH, "mpt_agent_motor_contract")
PATCH = _load_module(PATCH_PATH, "mpt_runtime_patch_contract")
MPT_AGENT_SOURCE = MPT_AGENT_PATH.read_text(encoding="utf-8")
PATCH_SOURCE = PATCH_PATH.read_text(encoding="utf-8")
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")


def _lock_error(message: str = "[WinError 32] O arquivo já está sendo usado por outro processo: 'final-1TEMP_MPY_wvf_snd.mp4'"):
    error = PermissionError(message)
    error.winerror = 32
    return error


# ---------------------------------------------------------------------------
# 1. Nome único por execução (a origem do WinError 32)
# ---------------------------------------------------------------------------


def test_unique_temp_audiofile_is_uuid_per_execution(tmp_path: Path):
    first = PATCH.unique_temp_audiofile_path(tmp_path / "final-1.mp4", tmp_path, "mp4")
    second = PATCH.unique_temp_audiofile_path(tmp_path / "final-1.mp4", tmp_path, "mp4")
    # Padrão pedido: final-1TEMP_MPY_<uuid4>_wvf_snd.mp4
    assert first.name.startswith("final-1TEMP_MPY_")
    assert first.name.endswith("_wvf_snd.mp4")
    assert len(first.stem.split("TEMP_MPY_", 1)[1].split("_wvf_snd", 1)[0]) == 32
    # Dois renders (ou dois «Refazer Vídeo» em paralelo) NUNCA colidem.
    assert first != second
    # Directório vazio = TEMP isolado do Thunderbolt (nunca o CWD do motor).
    isolated = PATCH.unique_temp_audiofile_path("final-1.mp4")
    assert isolated.parent == PATCH.thunderbolt_engine_temp_dir()


def test_write_wrapper_injects_unique_temp_and_retries_only_locks(monkeypatch):
    """A escrita do MoviePy ganha temp único e repete SÓ em WinError 32."""
    from moviepy.video.VideoClip import VideoClip

    calls: list[dict] = []

    # Espelho da assinatura real do MoviePy 2.x (o wrapper detecta o suporte
    # a remove_temp pela assinatura do que está a embrulhar).
    def flaky_inner(
        self,
        filename,
        *args,
        temp_audiofile=None,
        temp_audiofile_path="",
        remove_temp=True,
        **kwargs,
    ):
        calls.append(
            {
                "filename": filename,
                "temp_audiofile": temp_audiofile,
                "temp_audiofile_path": temp_audiofile_path,
                "remove_temp": remove_temp,
                **kwargs,
            }
        )
        if len(calls) == 1:
            raise _lock_error()
        return "video-pronto"

    monkeypatch.setattr(VideoClip, "write_videofile", flaky_inner, raising=False)
    assert PATCH.patch_moviepy_write_videofile() is True
    patched = VideoClip.write_videofile

    slept: list[float] = []
    monkeypatch.setattr(PATCH.time, "sleep", lambda seconds: slept.append(seconds))
    result = patched(object(), "final-1.mp4", temp_audiofile_path=str(ROOT))

    assert result == "video-pronto"
    assert len(calls) == 2  # bloqueio → repetição (não desiste, não cai para CPU)
    assert calls[0]["temp_audiofile"] != calls[1]["temp_audiofile"]  # nome fresco
    assert calls[0]["temp_audiofile"].endswith("_wvf_snd.mp4")
    assert "TEMP_MPY_" in calls[0]["temp_audiofile"]
    # A limpeza passa a ser nossa (com retry) — o os.remove do MoviePy não tem.
    assert calls[0].get("remove_temp") is False
    assert slept == [0.5]


def test_write_wrapper_never_retries_real_encoder_failures(monkeypatch):
    """Falha REAL de GPU/ffmpeg propaga de imediato (fallback legítimo)."""
    from moviepy.video.VideoClip import VideoClip

    calls: list[dict] = []

    def hard_fail(self, filename, *args, **kwargs):
        calls.append({"filename": filename, **kwargs})
        raise RuntimeError("No capable devices found")

    monkeypatch.setattr(VideoClip, "write_videofile", hard_fail, raising=False)
    assert PATCH.patch_moviepy_write_videofile() is True
    patched = VideoClip.write_videofile
    with pytest.raises(RuntimeError):
        patched(object(), "final-1.mp4", temp_audiofile_path=str(ROOT))
    assert len(calls) == 1  # zero retries: falha real ≠ bloqueio de ficheiro


def test_write_wrapper_respects_explicit_temp_audiofile(monkeypatch):
    """Se o motor (ou outrem) passar temp_audiofile explícito, é respeitado."""
    from moviepy.video.VideoClip import VideoClip

    calls: list[dict] = []

    def inner(self, filename, *args, **kwargs):
        calls.append(kwargs)
        return "ok"

    monkeypatch.setattr(VideoClip, "write_videofile", inner, raising=False)
    assert PATCH.patch_moviepy_write_videofile() is True
    explicit = str(ROOT / "meu-temp.mp4")
    VideoClip.write_videofile(object(), "final-1.mp4", temp_audiofile=explicit)
    assert calls[0]["temp_audiofile"] == explicit
    assert "remove_temp" not in calls[0]


# ---------------------------------------------------------------------------
# 2. Fallback falso-positivo: lock NÃO desativa NVENC
# ---------------------------------------------------------------------------


def _fake_video_service() -> ModuleType:
    module = ModuleType("app.services.video_probe")
    module.disabled: list[tuple[str, str]] = []
    module.attempts = {"writer": 0, "always_lock": False}

    def disable(codec: str, reason: str = ""):
        module.disabled.append((codec, reason))

    def writer(clip, output_file, codec, **kwargs):
        module.attempts["writer"] += 1
        if module.attempts["always_lock"]:
            raise _lock_error()
        if module.attempts["writer"] == 1:
            raise _lock_error()
        return codec

    module._disable_runtime_video_codec = disable
    module._write_videofile_with_codec_fallback = writer
    module._get_temp_audio_dir = lambda output_dir: str(output_dir)
    return module


def test_lock_error_never_disables_the_codec():
    service = _fake_video_service()
    assert PATCH.patch_mpt_video_service(service) is True
    # WinError 32 não é falha de GPU: codec intacto, render continua.
    service._disable_runtime_video_codec("h264_nvenc", str(_lock_error()))
    assert service.disabled == []
    # Falha REAL de encoder continua a desativar (fallback legítimo do motor).
    service._disable_runtime_video_codec("h264_nvenc", "No capable devices found")
    assert service.disabled == [("h264_nvenc", "No capable devices found")]


def test_writer_retries_same_codec_on_lock_and_never_reports_cpu_fallback():
    service = _fake_video_service()
    PATCH.patch_mpt_video_service(service)
    # Lock transtório: repete o MESMO codec (nome fresco pela camada 1) e
    # devolve-o — NADA de «fallback to libx264» no log do motor.
    result = service._write_videofile_with_codec_fallback(None, "final-1.mp4", "h264_nvenc")
    assert result == "h264_nvenc"
    assert service.attempts["writer"] == 2
    assert service.disabled == []
    # Lock persistente: falha honesta, sem desativar GPU nem sujar telemetria.
    service.attempts["always_lock"] = True
    with pytest.raises(PermissionError):
        service._write_videofile_with_codec_fallback(None, "final-1.mp4", "h264_nvenc")
    assert service.disabled == []


def test_temp_audio_dir_is_forced_to_the_isolated_directory():
    service = _fake_video_service()
    PATCH.patch_mpt_video_service(service)
    assert service._get_temp_audio_dir(r"C:\Users\danha\AppData\Roaming\MobaXterm\slash\tmp") == str(
        PATCH.thunderbolt_engine_temp_dir()
    )


def test_post_import_hook_patches_the_service_module(tmp_path: Path):
    """O bootstrap não importa o motor: o hook patcha na importação real."""
    package = tmp_path / "thunderbolt_probe_app" / "services"
    package.mkdir(parents=True)
    (tmp_path / "thunderbolt_probe_app" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "video.py").write_text(
        "def _disable_runtime_video_codec(codec, reason=''):\n"
        "    return (codec, reason)\n"
        "def _write_videofile_with_codec_fallback(clip, output_file, codec, **kwargs):\n"
        "    return codec\n"
        "def _get_temp_audio_dir(output_dir):\n"
        "    return output_dir\n",
        encoding="utf-8",
    )
    target = "thunderbolt_probe_app.services.video"
    sys.path.insert(0, str(tmp_path))
    meta_path_size = len(sys.meta_path)
    try:
        for name in [n for n in list(sys.modules) if n.startswith("thunderbolt_probe_app")]:
            del sys.modules[name]
        PATCH._install_post_import_hook(target)
        module = importlib.import_module(target)
        assert getattr(module._disable_runtime_video_codec, PATCH.LOCK_GUARD_MARKER, False)
        assert getattr(module._write_videofile_with_codec_fallback, PATCH.WRITER_RETRY_MARKER, False)
        assert module._get_temp_audio_dir("x") == str(PATCH.thunderbolt_engine_temp_dir())
        # Hook one-shot: sai do meta_path depois de disparar.
        assert len(sys.meta_path) == meta_path_size
    finally:
        sys.path.remove(str(tmp_path))
        for name in [n for n in list(sys.modules) if n.startswith("thunderbolt_probe_app")]:
            del sys.modules[name]
        assert len(sys.meta_path) == meta_path_size


# ---------------------------------------------------------------------------
# 3. Limpeza preventiva de órfãos (> 24 h)
# ---------------------------------------------------------------------------


def test_cleanup_removes_only_orphans_older_than_24h(tmp_path: Path):
    orphan = tmp_path / "final-1TEMP_MPY_deadbeef_wvf_snd.mp4"
    orphan.write_bytes(b"temp")
    active = tmp_path / "final-1TEMP_MPY_cafe1234_wvf_snd.mp4"
    active.write_bytes(b"temp")
    unrelated = tmp_path / "final-1.mp4"
    unrelated.write_bytes(b"video")
    past = time.time() - 25 * 3600
    os.utime(orphan, (past, past))

    removed = PATCH.cleanup_orphan_mpt_temp_files(max_age_hours=24, temp_dir=tmp_path)

    assert removed == 1
    assert not orphan.exists()
    assert active.exists() and unrelated.exists()


# ---------------------------------------------------------------------------
# 4. Spawn do motor: bootstrap do patch + TEMP isolado no env do Popen
# ---------------------------------------------------------------------------


def _fake_generation_environment(tmp_path: Path, monkeypatch, root: Path, captured: dict):
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    monkeypatch.setattr(MPT_AGENT.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(MPT_AGENT, "run_checked", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        MPT_AGENT, "_cleanup_orphan_engine_temp_files", lambda *a, **k: captured.setdefault("cleaned", 3)
    )
    monkeypatch.setattr(MPT_AGENT.time, "sleep", lambda _seconds: None)

    def fake_run(command, **_kwargs):
        if "--help" in command:
            return SimpleNamespace(
                returncode=0,
                stdout="options:\n  --video-source VIDEO_SOURCE\n",
                stderr="",
            )
        raise AssertionError("o spawn do motor passou a usar Popen (1.0.40)")

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        task_id = command[command.index("--task-id") + 1]
        output = root / "storage" / "tasks" / task_id / "final-1.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        return SimpleNamespace(pid=909, returncode=0, poll=lambda: 0)

    monkeypatch.setattr(MPT_AGENT.subprocess, "run", fake_run)
    monkeypatch.setattr(MPT_AGENT.subprocess, "Popen", fake_popen)


def test_generate_video_spawns_engine_with_patch_bootstrap_and_isolated_temp(
    tmp_path: Path, monkeypatch
):
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    captured: dict = {}
    _fake_generation_environment(tmp_path, monkeypatch, root, captured)

    videos, _task_dir, _log_path, _result_path = MPT_AGENT.generate_video(
        root, "Tema blindado", ["--video-source", "pexels"]
    )

    assert videos
    command = captured["command"]
    assert "-c" in command
    bootstrap = command[command.index("-c") + 1]
    # O bootstrap carrega e aplica o patch antes de executar o cli.py…
    assert "mpt_runtime_patch" in bootstrap
    assert "_mod.apply()" in bootstrap
    assert "runpy.run_path" in bootstrap and "cli.py" in bootstrap
    # …e os argumentos do motor seguem intactos depois do código.
    assert command[command.index("--video-source") + 1] == "pexels"
    # O ambiente do Popen tem SEMPRE o TEMP isolado do Thunderbolt.
    env = captured["kwargs"]["env"]
    isolated = str(MPT_AGENT._thunderbolt_temp_dir())
    assert env["TEMP"] == isolated and env["TMP"] == isolated
    # A limpeza preventiva de órfãos corre antes do render.
    assert captured.get("cleaned") == 3


def test_engine_spawn_environment_isolates_temp_even_without_ffmpeg(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("THUNDERBOLT_INHERITED_MARKER", "do-pai")
    environment = MPT_AGENT._engine_spawn_environment(None)
    isolated = str(MPT_AGENT._thunderbolt_temp_dir())
    assert environment["TEMP"] == isolated and environment["TMP"] == isolated
    assert environment["THUNDERBOLT_INHERITED_MARKER"] == "do-pai"
    # Cópia completa: SYSTEMROOT/PATH nunca são substituídos por um mínimo.
    assert "PATH" in environment


def test_ffmpeg_environment_also_isolates_temp(tmp_path: Path, monkeypatch):
    import json as _json

    fake = tmp_path / "ffmpeg.exe"
    fake.write_bytes(b"")
    config_path = tmp_path / "config.toml"
    # json.dumps produz uma basic string TOML válida com as barras invertidas
    # dos caminhos do Windows (igual ao _write_config dos testes NVENC).
    config_path.write_text(
        "[app]\nffmpeg_path = %s\n" % _json.dumps(str(fake)), encoding="utf-8"
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    environment = MPT_AGENT._ffmpeg_environment(config_path)
    isolated = str(MPT_AGENT._thunderbolt_temp_dir())
    assert environment["TEMP"] == isolated and environment["TMP"] == isolated
    assert environment["IMAGEIO_FFMPEG_EXE"] == str(fake)


# ---------------------------------------------------------------------------
# 5. Contratos de source — a barra do CI para refactores futuros
# ---------------------------------------------------------------------------


def test_motor_lock_source_contracts():
    # Camada 1 — nome único (uuid) e retry só em lock.
    assert "uuid.uuid4().hex" in PATCH_SOURCE
    assert PATCH.MPT_TEMP_AUDIO_PREFIX == "TEMP_MPY_"
    assert PATCH.MPT_TEMP_AUDIO_SUFFIX == "_wvf_snd"
    assert PATCH.WINDOWS_LOCK_ERROR == 32
    assert "is_windows_lock_error(exc)" in PATCH_SOURCE
    # Camada 2 — trava do fallback falso: lock não passa do guarda.
    assert "if is_windows_lock_error(reason):" in PATCH_SOURCE
    assert PATCH.LOCK_GUARD_MARKER in PATCH_SOURCE and PATCH.WRITER_RETRY_MARKER in PATCH_SOURCE
    # O patch NUNCA mexe no NVENC por conta própria — codecs não aparecem
    # aqui; uma falha real de encoder continua no caminho original.
    assert "h264_nvenc" not in PATCH_SOURCE and "libx264" not in PATCH_SOURCE
    # Camada 3 — TEMP isolado + limpeza de órfãos (> 24 h).
    assert PATCH.ORPHAN_MAX_AGE_HOURS == 24
    assert 'MPT_TEMP_AUDIO_GLOB = "*TEMP_MPY_*"' in PATCH_SOURCE


def test_agent_source_contracts_for_the_motor_lock():
    # Bootstrap do patch no spawn do motor…
    assert '"-c",' in MPT_AGENT_SOURCE and "_engine_bootstrap_code()" in MPT_AGENT_SOURCE
    assert "runpy" in MPT_AGENT_SOURCE
    # …TEMP/TMP isolados em TODOS os caminhos de ambiente do motor…
    assert 'environment["TEMP"] = isolated' in MPT_AGENT_SOURCE
    assert 'environment["TMP"] = isolated' in MPT_AGENT_SOURCE
    assert "env=_engine_spawn_environment(render_environment)," in MPT_AGENT_SOURCE
    # …limpeza preventiva antes do render…
    assert "_cleanup_orphan_engine_temp_files()" in MPT_AGENT_SOURCE
    # …e o fail-fast da 1.0.40 (queda REAL de GPU) continua intacto.
    assert MPT_AGENT.MPT_CODEC_FALLBACK_MARKERS == (
        "fallback to libx264",
        "was disabled after a runtime failure",
    )
    assert "Falha na GPU: NVENC indisponível" in MPT_AGENT_SOURCE


def test_worker_spawn_env_keeps_the_isolated_temp():
    """Camada 1.0.43 intacta: o worker isola TEMP/TMP no env do helper."""
    env_block = WORKER_SOURCE.split("env = os.environ.copy()", 1)[1].split(
        "card = active_llm_card", 1
    )[0]
    assert 'env["TEMP"]' in env_block and 'env["TMP"]' in env_block
    assert "thunderbolt_temp_dir()" in env_block
    assert 'env = os.environ.copy()' in WORKER_SOURCE
