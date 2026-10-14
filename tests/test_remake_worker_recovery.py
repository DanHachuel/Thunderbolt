"""Item 6 (0.9.94): cobertura de interrupção do worker DURANTE um remake.

Cenário: o utilizador refaz um vídeo antigo (migração de schema aplicada), o
worker morre a meio da remontagem. Verifica-se que (1) a recuperação marca a
tarefa como falhada com `worker_interrupted` e pausa a fila, (2) os artefactos
parciais sobrevivem intactos, (3) o Start do utilizador recupera a tarefa no
estágio de vídeo — sem recomeçar topic/roteiro do zero.
"""

from __future__ import annotations

from hermes_ui import pipeline_worker, storage
from hermes_ui.domain import remake_video_task, retry_task_with_current_settings, transition_task


def _isolate(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", root / "tiktok" / "prompts_master")
    monkeypatch.setattr(storage, "MEDIA_DOWNLOADS", root / "downloads")
    monkeypatch.setattr(pipeline_worker, "STORAGE", root)
    storage.ensure_storage()
    return root


def _legacy_task() -> dict:
    """Tarefa antiga (stage legado, orchestration em formato antigo) com
    roteiro, tags, thumbnail, voz e artefactos que têm de sobreviver."""
    return {
        "id": "video-remake-crash",
        "state": "done",
        "stage": "edit",
        "script": "roteiro preservado",
        "topic": "Tema original",
        "blueprint_id": "bp-keep",
        "tags": ["tag1"],
        "voice": "pt-BR-A",
        "artifacts": {
            "script": "/tmp/roteiro.md",
            "thumbnail": "/tmp/thumb.png",
            "video": "/tmp/old.mp4",
            "audio": "/tmp/old.mp3",
        },
        "orchestration": {
            "name": "old",
            "stage_order": ["topic", "edit"],
            "current_stage": "edit",
            "completed_stages": ["topic", "edit"],
            "resumable": True,
        },
    }


def _simulate_worker_death_mid_remake(task_id: str, monkeypatch) -> bool:
    """Worker a meio do remake: tarefa 'doing' em 'video' + worker morto."""
    transition_task(task_id, "doing", "video")
    storage.write_json(pipeline_worker.PIPELINE_LOG_FILENAME, {
        "status": "running",
        "worker_pid": 987654321,
        "last_task_id": task_id,
    })
    monkeypatch.setattr(pipeline_worker, "_pid_alive", lambda _pid, **_kwargs: False)
    return pipeline_worker._recover_interrupted_pipeline_worker()


def test_remake_interrupted_worker_recovers_correctly(tmp_path, monkeypatch):
    """Worker morre durante remake → tarefa recuperada do estágio correto."""
    _isolate(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [_legacy_task()])

    assert remake_video_task("video-remake-crash") is not None
    assert _simulate_worker_death_mid_remake("video-remake-crash", monkeypatch) is True

    task = storage.read_json("tasks.json")[0]
    assert task["state"] == "failed"           # marcada como falhada pelo recovery
    assert task["worker_interrupted"] is True
    status = storage.read_json(pipeline_worker.PIPELINE_LOG_FILENAME)
    assert status["auto_paused"] is True       # fila pausada por segurança
    assert pipeline_worker.resume_pipeline_worker() is True

    # O Start do utilizador (retry) recoloca a tarefa na fila no estágio certo.
    retried = retry_task_with_current_settings("video-remake-crash")
    assert retried["state"] == "to_do"
    assert retried["stage"] == "video"
    assert retried["orchestration"]["current_stage"] == "video"
    assert retried["worker_interrupted"] is True  # marcador histórico mantido


def test_remake_partial_artifacts_preserved_after_recovery(tmp_path, monkeypatch):
    """Artefactos baixados antes da interrupção continuam válidos."""
    _isolate(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [_legacy_task()])

    remake_video_task("video-remake-crash")
    _simulate_worker_death_mid_remake("video-remake-crash", monkeypatch)
    retry_task_with_current_settings("video-remake-crash")

    task = storage.read_json("tasks.json")[0]
    # O remake invalidou apenas vídeo/áudio; script e thumbnail sobrevivem à
    # interrupção e às duas transições de recuperação sem qualquer corrupção.
    assert task["artifacts"] == {"script": "/tmp/roteiro.md", "thumbnail": "/tmp/thumb.png"}
    assert task["script"] == "roteiro preservado"
    assert task["topic"] == "Tema original"
    assert task["blueprint_id"] == "bp-keep"
    assert task["tags"] == ["tag1"]
    assert task["voice"] == "pt-BR-A"


def test_remake_does_not_restart_from_scratch_after_recovery(tmp_path, monkeypatch):
    """Recuperação não deve reiniciar estágios já concluídos."""
    _isolate(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [_legacy_task()])

    remake_video_task("video-remake-crash")
    _simulate_worker_death_mid_remake("video-remake-crash", monkeypatch)
    retried = retry_task_with_current_settings("video-remake-crash")

    # A tarefa continua no estágio de vídeo: o roteiro e o tema persistidos
    # fazem a cascata artefacto-dirigida saltar topic/script — nada é
    # regenerado do zero.
    assert retried["stage"] == "video"
    assert retried["orchestration"]["current_stage"] == "video"
    assert retried["topic"] == "Tema original"
    assert retried["script"] == "roteiro preservado"
    artifacts = retried.get("artifacts") or {}
    assert "video" not in artifacts   # só o render de vídeo é que é refeito
    assert "audio" not in artifacts
    assert artifacts.get("script") == "/tmp/roteiro.md"
