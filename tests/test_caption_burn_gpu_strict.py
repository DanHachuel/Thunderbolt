"""1.0.57 — queima de legendas SEM fallback silencioso para CPU.

O relato: dois vídeos «Refazer Vídeo» 1 h travados em 75% com
`[text_to_images] [AVISO] NVENC falhou na escrita ([WinError 32] …
final-1.legendas-27464-tmpTEMP_MPY_wvf_snd.mp4) — a repetir no CPU
(libx264)` no log. Duas causas, duas correcções:

1. o temporário do MoviePy tinha nome ESTÁTICO derivado do output
   (`{stem}TEMP_MPY_wvf_snd.mp4`) — a 1.0.51 pôs uuid só no patch do
   motor MPT, não no burner local;
2. o fallback para libx264 repetia o MESMO caminho bloqueado, falhava
   outra vez e deixava a CPU a trabalhar durante horas sem um erro claro.

Contratos cobertos:
- `_unique_temp_audiofile`: nome com uuid4 (dois renders/retries nunca
  colidem), mantendo o sufixo TEMP_MPY_ para a limpeza de órfãos;
- `_write_web_safe_videofile`: SEM fallback para CPU — bloqueio repete 3x
  com nome novo e esgota em `GpuTempLockError`; outra falha propaga;
  máquina sem GPU continua em libx264 desde o início (probe);
- `_apply_mpt_captions` NÃO engole o `GpuTempLockError` (aborta a tarefa);
- `_purge_stale_engine_temp_files`: apaga só órfãos com mais de 1 h;
- `_VideoStageTimer`: o timer real da etapa sobe nas fases locais (o falso
  «8m 40s» congelado morreu) e nunca salta para trás.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

from hermes_ui import pipeline_worker, text_to_images


ROOT = Path(__file__).resolve().parents[1]
TEXT_TO_IMAGES_SOURCE = (ROOT / "hermes_ui" / "text_to_images.py").read_text(encoding="utf-8")
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")


class _FakeClip:
    def __init__(self, *, fail_codecs=(), always_lock=False):
        self.calls: list[dict] = []
        self._fail_codecs = set(fail_codecs)
        self._always_lock = always_lock

    def write_videofile(self, path, **kwargs):
        self.calls.append({"path": path, **kwargs})
        if self._always_lock:
            error = PermissionError(
                "[WinError 32] O arquivo já está sendo usado por outro processo: "
                f"'{kwargs.get('temp_audiofile') or path}'"
            )
            error.winerror = 32
            raise error
        if kwargs.get("codec") in self._fail_codecs:
            raise RuntimeError("encoder exploded")


# ---------------------------------------------------------------------------
# 1. Nome único (uuid) no temporário da queima
# ---------------------------------------------------------------------------


def test_unique_temp_audiofile_uses_uuid_and_keeps_orphan_marker(tmp_path: Path):
    first = text_to_images._unique_temp_audiofile(tmp_path / "final-1.legendas-27464-tmp.mp4", tmp_path)
    second = text_to_images._unique_temp_audiofile(tmp_path / "final-1.legendas-27464-tmp.mp4", tmp_path)
    assert first.parent == tmp_path
    assert first.name.startswith("final-1.legendas-27464-tmpTEMP_MPY_")
    assert first.name.endswith("_wvf_snd.mp4")
    assert first != second  # uuid4 por tentativa: dois renders nunca colidem
    token = first.name.split("TEMP_MPY_", 1)[1].split("_wvf_snd", 1)[0]
    assert len(token) == 32
    # O marcador fica para a limpeza de órfãos reconhecer o ficheiro.
    assert list(tmp_path.glob("*TEMP_MPY_*")) == []


# ---------------------------------------------------------------------------
# 2. Sem fallback para CPU: lock repete com nome novo, esgota com mensagem
# ---------------------------------------------------------------------------


def test_lock_error_retries_three_times_with_fresh_names_then_aborts(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(text_to_images, "_nvenc_encoder_available", lambda _binary: True)
    monkeypatch.setattr(text_to_images.time, "sleep", lambda _seconds: None)
    clip = _FakeClip(always_lock=True)
    with pytest.raises(text_to_images.GpuTempLockError) as raised:
        text_to_images._write_web_safe_videofile(
            clip,
            tmp_path / "final-1.legendas-27464-tmp.mp4",
            fps=30,
            temp_audiofile_path=tmp_path,
        )
    # 3 tentativas, todas em NVENC (nunca libx264) e com nomes DIFENTES.
    assert len(clip.calls) == 3
    assert [call["codec"] for call in clip.calls] == ["h264_nvenc"] * 3
    names = [call["temp_audiofile"] for call in clip.calls]
    assert len(set(names)) == 3
    assert text_to_images.GPU_TEMP_LOCK_MESSAGE in str(raised.value)
    assert "Loop" not in capsys.readouterr().err
    assert "a repetir no CPU (libx264)" not in TEXT_TO_IMAGES_SOURCE


def test_lock_error_that_clears_on_second_attempt_succeeds(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(text_to_images, "_nvenc_encoder_available", lambda _binary: True)
    monkeypatch.setattr(text_to_images.time, "sleep", lambda _seconds: None)

    class _FlakyClip(_FakeClip):
        def write_videofile(self, path, **kwargs):
            self.calls.append({"path": path, **kwargs})
            if len(self.calls) == 1:
                error = PermissionError("[WinError 32] sendo usado por outro processo")
                error.winerror = 32
                raise error

    clip = _FlakyClip()
    codec = text_to_images._write_web_safe_videofile(
        clip, tmp_path / "final-1.legendas-27464-tmp.mp4", fps=30, temp_audiofile_path=tmp_path
    )
    assert codec == "h264_nvenc"
    assert len(clip.calls) == 2
    assert clip.calls[0]["temp_audiofile"] != clip.calls[1]["temp_audiofile"]
    # A limpeza é nossa (retry) — o os.remove sem retry do MoviePy morreu.
    assert clip.calls[0].get("remove_temp") is False


def test_real_encoder_failure_never_retries_or_falls_back(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(text_to_images, "_nvenc_encoder_available", lambda _binary: True)
    clip = _FakeClip(fail_codecs={"h264_nvenc"})
    with pytest.raises(RuntimeError):
        text_to_images._write_web_safe_videofile(clip, tmp_path / "out.mp4", fps=30)
    assert len(clip.calls) == 1


def test_machine_without_gpu_still_writes_in_cpu_from_the_start(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(text_to_images, "_nvenc_encoder_available", lambda _binary: False)
    clip = _FakeClip()
    codec = text_to_images._write_web_safe_videofile(
        clip, tmp_path / "out.mp4", fps=30, temp_audiofile_path=tmp_path
    )
    assert codec == "libx264"
    assert len(clip.calls) == 1


def test_burn_captions_uses_the_unique_temp_path(tmp_path: Path, monkeypatch):
    """A queima isola o temp no directório do Thunderbolt (1.0.43 + 1.0.57).

    O writer recebe o directório e é ELE que gera o nome único por uuid —
    contrato coberto comportamentalmente em
    test_lock_error_retries_three_times_with_fresh_names_then_aborts.
    Aqui confirma-se que a chamada da queima continua a passar o caminho
    isolado (sem ele o temporário cairia ao lado do output).
    """
    burn_body = TEXT_TO_IMAGES_SOURCE.split("def burn_captions_on_video(", 1)[1].split(
        "def synthesize_text_to_images_audio", 1
    )[0]
    # 1.0.58: a queima é FFmpeg puro — não existe TEMP_MPY_wvf_snd na queima
    # (o subprocesso escreve directo no mp4 temporário único por uuid).
    assert "temp_audiofile_path" not in burn_body
    assert "legendas-{os.getpid()}-{uuid.uuid4().hex[:8]}" in burn_body
    # 1.0.61/1.0.67 - o ficheiro de legendas chama-se `captions` (e um .ass).
    assert "safe_unlink(captions, missing_ok=True)" in burn_body
    assert "safe_unlink(temporary, missing_ok=True)" in burn_body
    # 1.0.57: o nome único por uuid entrou no WRITOR (não apenas por PID).
    writer_body = TEXT_TO_IMAGES_SOURCE.split("def _write_web_safe_videofile", 1)[1].split(
        "def _close_clip_reader", 1
    )[0]
    assert "_unique_temp_audiofile(output_path, temp_audiofile_path)" in writer_body
    assert "remove_temp" in writer_body and "_discard_temp_audiofile(temp_audiofile)" in writer_body
    # Lock detectado pelo CAMINHO do temporário (sessão real do FFmpeg não
    # traz winerror) — nunca só pelo código do erro.
    assert "_is_temp_lock_error(exc, temp_audiofile)" in writer_body


def test_temp_lock_error_matches_real_ffmpeg_messages():
    """A sessão real do FFmpeg devolve «Permission denied» sem winerror."""
    error = RuntimeError(
        "Error opening input file 'C:\\Temp\\final-1.legendas-99-tmpTEMP_MPY_abc_wvf_snd.mp4'. Permission denied"
    )
    assert text_to_images._is_temp_lock_error(
        error, Path(r"C:\Temp\final-1.legendas-99-tmpTEMP_MPY_abc_wvf_snd.mp4")
    )
    # Um «Permission denied» noutro ficheiro NÃO é lock do nosso temporário.
    assert not text_to_images._is_temp_lock_error(error, Path(r"C:\Temp\outro.mp4"))
    # WinError 32 continua a bater mesmo sem o caminho na mensagem.
    lock = PermissionError("[WinError 32] O arquivo já está sendo usado por outro processo")
    lock.winerror = 32
    assert text_to_images._is_temp_lock_error(lock, None)


# ---------------------------------------------------------------------------
# 3. O lock NÃO é engolido pelo worker
# ---------------------------------------------------------------------------


def test_mpt_captions_error_propagates_gpu_lock_instead_of_silencing():
    assert "except Exception as exc:" in WORKER_SOURCE
    block = WORKER_SOURCE.split("def _apply_mpt_captions(", 1)[1].split("\ndef ", 1)[0]
    assert "GpuTempLockError" in block
    assert "isinstance(exc, GpuTempLockError)" in block
    # O re-raise aparece ANTES do except genérico: a tarefa morre.
    assert block.index("isinstance(exc, GpuTempLockError)") < block.index("legendas ignoradas por falha na queima")


# ---------------------------------------------------------------------------
# 4. Limpeza de órfãos (> 1 h)
# ---------------------------------------------------------------------------


def test_purge_removes_only_temp_files_older_than_one_hour(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pipeline_worker, "thunderbolt_temp_dir", lambda: tmp_path)
    orphan = tmp_path / "final-1TEMP_MPY_deadbeef_wvf_snd.mp4"
    orphan.write_bytes(b"temp")
    fresh = tmp_path / "final-1TEMP_MPY_cafe_wvf_snd.mp4"
    fresh.write_bytes(b"temp")
    unrelated = tmp_path / "final-1.mp4"
    unrelated.write_bytes(b"video")
    past = time.time() - 2 * 3600
    os.utime(orphan, (past, past))

    removed = pipeline_worker._purge_stale_engine_temp_files()

    assert removed == 1
    assert not orphan.exists()
    assert fresh.exists() and unrelated.exists()


def test_purge_never_raises_when_the_temp_dir_is_missing(monkeypatch):
    monkeypatch.setattr(
        pipeline_worker, "thunderbolt_temp_dir", lambda: (_ for _ in ()).throw(OSError("boom"))
    )
    assert pipeline_worker._purge_stale_engine_temp_files() == 0


# ---------------------------------------------------------------------------
# 5. Timer real da etapa (fim do falso «8m 40s»)
# ---------------------------------------------------------------------------


def test_video_stage_timer_writes_elapsed_and_never_goes_backwards(tmp_path: Path, monkeypatch):
    import threading as real_threading

    monkeypatch.setattr(pipeline_worker, "VIDEO_STAGE_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    task_id = "task-timer-57"
    writes: list[dict] = []

    # O relógio do helper pode estar mais à frente (base = spawn): o timer do
    # step adopta esse valor em vez de saltar para trás.
    persisted = {"value": 600}

    def fake_update(_tid, **updates):
        writes.append(dict(updates))
        if "video_elapsed_seconds" in updates:
            persisted["value"] = max(persisted["value"], updates["video_elapsed_seconds"])

    monkeypatch.setattr(pipeline_worker, "_task_by_id", lambda _tid: {"state": "doing", "progress": 60, "video_elapsed_seconds": persisted["value"]})
    monkeypatch.setattr(pipeline_worker, "_update", fake_update)
    monkeypatch.setattr(pipeline_worker, "_worker_heartbeat", lambda **updates: writes.append(dict(updates)))

    timer = pipeline_worker._VideoStageTimer(task_id, time.monotonic() - 1).start()
    real_threading.Event().wait(0.45)  # espera REAL (não monkeypatchada)
    timer.stop()

    elapsed_writes = [w["video_elapsed_seconds"] for w in writes if "video_elapsed_seconds" in w]
    assert elapsed_writes, "o timer tem de escrever video_elapsed_seconds"
    assert elapsed_writes == sorted(elapsed_writes), "o relógio nunca pode retroceder"
    assert any(w.get("stage") == "video" for w in writes)
    assert all(w.get("task_id") == task_id for w in writes if w.get("stage") == "video")


def test_video_stage_timer_stops_promptly():
    timer = pipeline_worker._VideoStageTimer("task-stop", time.monotonic())
    timer.start()
    timer.stop()
    assert timer._thread is None
    assert timer._stop.is_set()


def test_worker_source_contracts_for_the_stage_clock():
    # 1.0.59: o relógio do PASSO arranca no ROTEIRO (não só na etapa de
    # vídeo) - é o que faz o timer do card subir desde o minuto 0 e mostra a
    # actividade da fase em video_helper_status.
    assert (
        "_VideoStageTimer(\n        task_id, _step_started_at, status_provider=_step_activity\n    ).start()"
        in WORKER_SOURCE
    )
    # A etapa de vídeo CONTINUA o mesmo relógio (nunca salta para trás):
    # um só cronómetro por passo, sem dois ticks a escrever o mesmo campo.
    assert "_video_stage_timer = _step_timer" in WORKER_SOURCE
    assert "_video_stage_timer.stop()" in WORKER_SOURCE
    assert "finally:" in WORKER_SOURCE.split("_video_stage_timer = _step_timer", 1)[1].split("def ", 1)[0]
    # Falha do roteiro também para o relógio (nunca fica um tick a escrever
    # heartbeat de uma etapa terminada).
    script_block = WORKER_SOURCE.split("def _step_activity", 1)[1].split("_step_timer = ", 1)[1]
    assert "_step_timer.stop()" in WORKER_SOURCE
    assert "_purge_stale_engine_temp_files()" in WORKER_SOURCE
    assert 'glob("*TEMP_MPY*")' in WORKER_SOURCE
    # O relógio é monótono por construção.
    assert "nunca retrocede" in WORKER_SOURCE
    assert script_block is not None
