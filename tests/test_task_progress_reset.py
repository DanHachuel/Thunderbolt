"""1.0.78 — tarefa re-enfileirada (retry/remake) volta a 0% de progresso.

Regressão do relato do utilizador: uma tarefa falhou no roteiro com 18% de
progresso; ao clicar em «Refazer Vídeo» o estado voltou a ``to_do`` mas a
barra continuou a mostrar progresso herdado (o remake escrevia 50%!). Uma
tarefa na fila tem de mostrar 0% / «Aguardando na fila» até começar a rodar
(``doing``) — no JSON e na UI.
"""

from __future__ import annotations

from pathlib import Path


MAIN_SOURCE = Path(__file__).resolve().parents[1] / "app" / "main.py"
MAIN_SOURCE = MAIN_SOURCE.read_text(encoding="utf-8")
DOMAIN_SOURCE = (Path(__file__).resolve().parents[1] / "hermes_ui" / "domain.py").read_text(encoding="utf-8")


def _storage(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    return storage


def _failed_task(**extra):
    task = {
        "id": "video-progress",
        "channel_id": "",
        "state": "failed",
        "stage": "script",
        "progress": 18,
        "error": "O provider LLM devolveu um documento sem conteúdo.",
        "video_helper_status": "a gerar imagens e narração",
        "video_elapsed_seconds": 742,
        "upload_elapsed_seconds": 35,
    }
    task.update(extra)
    return task


# ---------------------------------------------------------------------------
# Backend: retry/remake zeram o progresso no JSON
# ---------------------------------------------------------------------------


def test_retry_resets_progress_to_zero(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    from hermes_ui.domain import retry_task_with_current_settings

    storage.write_json("tasks.json", [_failed_task()])

    retried = retry_task_with_current_settings("video-progress")

    assert retried is not None
    assert retried["state"] == "to_do"
    assert retried["progress"] == 0
    assert retried["video_helper_status"] == "Aguardando na fila"
    assert retried["video_elapsed_seconds"] == 0
    assert retried["upload_elapsed_seconds"] == 0
    assert retried["error"] is None
    # e o JSON persistido confirma (não é só o valor devolvido).
    persisted = storage.read_json("tasks.json")[0]
    assert persisted["state"] == "to_do"
    assert persisted["progress"] == 0


def test_remake_resets_progress_to_zero(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    from hermes_ui.domain import remake_video_task

    storage.write_json("tasks.json", [_failed_task(progress=50, video_ready=True)])

    remade = remake_video_task("video-progress")

    assert remade is not None
    assert remade["state"] == "to_do"
    # 1.0.78 - era 50: a barra pulava para metade com a tarefa na fila.
    assert remade["progress"] == 0
    assert remade["video_helper_status"] == "Aguardando na fila"
    assert remade["video_elapsed_seconds"] == 0
    assert remade["upload_elapsed_seconds"] == 0
    assert remade["video_ready"] is False
    # o conteúdo criativo continua (o remake reaproveita roteiro/thumbnail).
    assert remade["stage"] == "video"
    persisted = storage.read_json("tasks.json")[0]
    assert persisted["progress"] == 0
    assert persisted["state"] == "to_do"


def test_retry_of_blocked_task_also_resets_progress(tmp_path, monkeypatch):
    storage = _storage(tmp_path, monkeypatch)
    from hermes_ui.domain import retry_task_with_current_settings

    storage.write_json("tasks.json", [_failed_task(state="blocked", stop_reason="upload_uncertain", upload_uncertain=True, confirm_upload_uncertain=True)])

    retried = retry_task_with_current_settings("video-progress", confirm_upload_uncertain=True)

    assert retried["state"] == "to_do"
    assert retried["progress"] == 0
    assert retried["video_elapsed_seconds"] == 0


# ---------------------------------------------------------------------------
# UI: o card força 0% / «Aguardando na fila» quando o estado é to_do
# ---------------------------------------------------------------------------


def test_ui_progress_is_zero_for_queued_tasks():
    progress_block = MAIN_SOURCE.split("def _video_task_progress(", 1)[1].split("def _render_video_task_state", 1)[0]
    assert 'if state == "to_do":' in progress_block
    assert "return 0" in progress_block
    # a regra vem ANTES da derivação por artefactos (vídeo+thumbnail ≠ 100% na fila).
    assert progress_block.index('if state == "to_do":') < progress_block.index("return 100")


def test_ui_state_render_shows_queue_text_for_to_do():
    render_block = MAIN_SOURCE.split("def _render_video_task_state(", 1)[1].split("def _create_video_now_from_channel", 1)[0]
    assert 'if state == "to_do":' in render_block
    assert 'st.progress(0, text="Aguardando na fila")' in render_block


def test_worker_still_starts_queued_tasks_at_the_script_stage():
    """Regressão invertida: zerar o progresso não pode travar o worker — a
    fase de roteiro arranca em max(18, ...) sobre 0."""
    from hermes_ui import pipeline_worker

    worker_source = Path(pipeline_worker.__file__).read_text(encoding="utf-8")
    assert 'progress=max(18, int(task.get("progress") or 0))' in worker_source
