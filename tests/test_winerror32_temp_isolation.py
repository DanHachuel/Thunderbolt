"""1.0.43 — WinError 32 (file lock no MoviePy) + TEMP/TMP isolados.

Contratos cobertos:
- ``thunderbolt_temp_dir()`` aponta para LOCALAPPDATA/THUNDERBOLT/temp
  (nunca para a pasta instável do MobaXterm herdada pelo launcher);
- o env do spawn do MPT no worker sobrescreve TEMP/TMP para esse directório
  (mantendo SYSTEMROOT/herança — restrição da 1.0.37/38);
- ``safe_file_op``/``safe_replace``/``safe_unlink`` com retry em WinError 32
  (backoff 0.5/1/2/4 s), propagando qualquer outro erro de imediato;
- a queima de legendas isola o temp do MoviePy (temp_audiofile_path), usa
- nome temporário único por PID, fecha o reader explicitamente e substitui
- com retry; o normalizador streamable também protegido.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_ui import fs_safe, pipeline_worker, storage as ui_storage, text_to_images


ROOT = Path(__file__).resolve().parents[1]
TEXT_TO_IMAGES_SOURCE = (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Directório temporário isolado
# ---------------------------------------------------------------------------


def test_thunderbolt_temp_dir_is_isolated_from_mobaxterm(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("TEMP", r"C:\Users\danha\AppData\Roaming\MobaXterm\...\tmp")
    monkeypatch.setenv("TMP", r"C:\Users\danha\AppData\Roaming\MobaXterm\...\tmp")
    temp_dir = ui_storage.thunderbolt_temp_dir()
    assert temp_dir == tmp_path / "local" / "THUNDERBOLT" / "temp"
    assert temp_dir.is_dir()
    assert "MobaXterm" not in str(temp_dir)


def test_thunderbolt_temp_dir_falls_back_when_not_creatable(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "")
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    # Sem base possível: cai no temp do sistema sem rebentar (nunca falha).
    temp_dir = ui_storage.thunderbolt_temp_dir()
    assert temp_dir.is_dir() or temp_dir.exists()


# ---------------------------------------------------------------------------
# Retry em WinError 32 (safe_file_op / safe_replace / safe_unlink)
# ---------------------------------------------------------------------------


def test_safe_file_op_retries_winerror_32_then_succeeds(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(fs_safe.time, "sleep", lambda seconds: slept.append(seconds))
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            error = OSError("a ser usado por outro processo")
            error.winerror = 32
            raise error
        return "ok"

    assert fs_safe.safe_file_op(flaky) == "ok"
    assert attempts["count"] == 3
    # Backoff 0.5, 1, 2, 4 s — as duas primeiras tentativas falharam.
    assert slept == [0.5, 1.0]


def test_safe_file_op_raises_non_lock_errors_immediately(monkeypatch):
    monkeypatch.setattr(fs_safe.time, "sleep", lambda _seconds: pytest.fail("não deve retentar"))
    error = PermissionError("negado")
    error.winerror = 5  # acesso negado NÃO é lock: propaga de imediato

    def denied():
        raise error

    with pytest.raises(PermissionError):
        fs_safe.safe_file_op(denied)


def test_safe_file_op_gives_up_after_max_retries(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(fs_safe.time, "sleep", lambda seconds: slept.append(seconds))
    error = OSError("sempre bloqueado")
    error.winerror = 32

    def always_locked():
        raise error

    with pytest.raises(OSError):
        fs_safe.safe_file_op(always_locked, max_retries=3)
    assert slept == [0.5, 1.0]  # 3 tentativas => 2 esperas


def test_safe_replace_retries_and_replaces(tmp_path: Path, monkeypatch):
    source = tmp_path / "fonte.mp4"
    destination = tmp_path / "destino.mp4"
    source.write_bytes(b"novo")
    destination.write_bytes(b"velho")
    monkeypatch.setattr(fs_safe.time, "sleep", lambda _seconds: None)
    real_replace = os.replace
    state = {"falhas": 1}

    def flaky_replace(src, dst):
        if state["falhas"]:
            state["falhas"] -= 1
            error = OSError("bloqueado")
            error.winerror = 32
            raise error
        return real_replace(src, dst)

    monkeypatch.setattr(fs_safe.os, "replace", flaky_replace)
    fs_safe.safe_replace(source, destination)
    assert destination.read_bytes() == b"novo"


def test_safe_unlink_is_noop_for_missing_file(tmp_path: Path):
    assert fs_safe.safe_unlink(tmp_path / "nao-existe.mp4") is False
    target = tmp_path / "existe.mp4"
    target.write_bytes(b"x")
    assert fs_safe.safe_unlink(target) is True
    assert not target.exists()


def test_safe_unlink_retries_winerror_32(tmp_path: Path, monkeypatch):
    target = tmp_path / "bloqueado.mp4"
    target.write_bytes(b"x")
    monkeypatch.setattr(fs_safe.time, "sleep", lambda _seconds: None)
    real_unlink = Path.unlink
    state = {"falhas": 2}

    def flaky_unlink(self, *args, **kwargs):
        if self == target and state["falhas"]:
            state["falhas"] -= 1
            error = OSError("bloqueado")
            error.winerror = 32
            raise error
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    assert fs_safe.safe_unlink(target) is True


# ---------------------------------------------------------------------------
# Env do spawn: TEMP/TMP isolados (e SYSTEMROOT intacto)
# ---------------------------------------------------------------------------


def test_worker_process_temp_isolation_guard():
    source = WORKER_SOURCE
    assert "def _isolate_worker_process_temp()" in source
    assert '"mobaxterm" in inherited' in source
    assert "_isolate_worker_process_temp()" in source


def test_worker_process_temp_env_is_isolated_after_import(monkeypatch):
    monkeypatch.setenv("TEMP", r"C:\Users\danha\AppData\Roaming\MobaXterm\slash\tmp")
    monkeypatch.setenv("TMP", r"C:\Users\danha\AppData\Roaming\MobaXterm\slash\tmp")
    monkeypatch.setenv("LOCALAPPDATA", str(ROOT / "storage" / "_temp_test"))
    import importlib

    module = importlib.reload(pipeline_worker)
    assert module.os.environ["TEMP"] == str(ui_storage.thunderbolt_temp_dir())
    assert "MobaXterm" not in module.os.environ["TEMP"]


def test_worker_process_temp_respects_healthy_temp(monkeypatch):
    monkeypatch.setenv("TEMP", r"C:\Users\danha\AppData\Local\Temp")
    monkeypatch.setenv("TMP", r"C:\Users\danha\AppData\Local\Temp")
    import importlib

    module = importlib.reload(pipeline_worker)
    assert module.os.environ["TEMP"] == r"C:\Users\danha\AppData\Local\Temp"


def test_worker_env_contract_isolates_temp_and_preserves_systemroot():
    env_block = WORKER_SOURCE.split("env = os.environ.copy()", 1)[1].split("card = active_llm_card", 1)[0]
    assert 'env["TEMP"]' in env_block and 'env["TMP"]' in env_block
    assert "thunderbolt_temp_dir()" in env_block
    # O SYSTEMROOT/herança da 1.0.37/38 não podem ser substituídos por um
    # dicionário mínimo — a injecção parte sempre da cópia completa.
    assert 'env = os.environ.copy()' in WORKER_SOURCE
    assert 'return {"IMAGEIO_FFMPEG_EXE"' not in (
        (ROOT / "seed" / "skills" / "mpt_agent.py").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Queima de legendas: temp isolado, nome único, reader fechado, replace seguro
# ---------------------------------------------------------------------------


def test_burn_contracts_for_winerror_32():
    burn_body = TEXT_TO_IMAGES_SOURCE.split("def burn_captions_on_video", 1)[1].split(
        "def synthesize_text_to_images_audio", 1
    )[0]
    assert "temp_audiofile_path=thunderbolt_temp_dir()" in burn_body
    assert "legendas-{os.getpid()}-tmp.mp4" in burn_body  # nome único por PID
    assert "_close_clip_reader(video)" in burn_body      # reader fechado antes
    assert "safe_replace(temporary, output)" in burn_body
    assert "safe_unlink(temporary, missing_ok=True)" in burn_body


def test_write_web_safe_videofile_accepts_temp_dir(tmp_path: Path, monkeypatch):
    class _FakeClip:
        def __init__(self):
            self.calls: list[dict] = []

        def write_videofile(self, path, **kwargs):
            self.calls.append({"path": path, **kwargs})

    monkeypatch.setattr(text_to_images, "_nvenc_encoder_available", lambda _ffmpeg: True)
    clip = _FakeClip()
    temp_dir = tmp_path / "temp-isolado"
    codec = text_to_images._write_web_safe_videofile(
        clip, tmp_path / "out.mp4", fps=30, temp_audiofile_path=temp_dir
    )
    assert codec == "h264_nvenc"
    assert clip.calls[0]["temp_audiofile_path"] == str(temp_dir)
    assert clip.calls[0]["ffmpeg_params"] == text_to_images.WEB_SAFE_MP4_FFMPEG_PARAMS


def test_close_clip_reader_is_tolerant_of_plain_objects():
    class _Reader:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class _Audio:
        def __init__(self):
            self.reader = _Reader()

    class _Clip:
        def __init__(self):
            self.reader = _Reader()
            self.audio = _Audio()

    clip = _Clip()
    text_to_images._close_clip_reader(clip)
    assert clip.reader.closed and clip.audio.reader.closed
    # Nunca rebenta com objectos sem reader (stills/áudio puro).
    text_to_images._close_clip_reader(object())


def test_streamable_normalizer_uses_safe_file_ops():
    normalizer = WORKER_SOURCE.split("def _ensure_streamable_mp4", 1)[1].split("def _run_remotion_video", 1)[0]
    assert "safe_replace(target, path)" in normalizer
    assert "safe_unlink(target)" in normalizer
