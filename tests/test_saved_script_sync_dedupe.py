"""Testes do dedupe do sync de roteiros (1.0.08 — falsos órfãos).

O _sync_saved_scripts_to_youtube_automation expõe cada roteiro guardado como
uma tarefa manual — mas não pode criar uma to_do para um roteiro que já tem
dona: a tarefa do pipeline que o gerou (carimbando script_document_id no
artefacto, ou, nas antigas, deixando só o path roteiro-<slug>-<id>.md).
"""
from __future__ import annotations

import json
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PIPELINE_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")

DOC_ID = "e9fb8f3ee024"
DOC_TITLE = "The Hidden Danger of Only Praying During a Crisis"
NOW = "2026-10-19T02:25:26+00:00"


def _isolate_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from hermes_ui import storage

    root = tmp_path / "storage"
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(root))
    storage.STORAGE = root
    storage.STATE = root / "state"
    storage.BLUEPRINTS = root / "blueprints"
    storage.STATE.mkdir(parents=True, exist_ok=True)
    storage._ensured_storage_root = None
    return root


def _write_script_document(root: Path, *, doc_id: str = DOC_ID, title: str = DOC_TITLE) -> Path:
    from hermes_ui import storage

    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    path = scripts_dir / f"roteiro-the-hidden-danger-of-only-praying-{doc_id}.md"
    path.write_text(
        "---\n"
        f"id: {doc_id}\n"
        "type: video_script\n"
        f"title: {title}\n"
        "language: pt\n"
        "channel: Canal Teste\n"
        "blueprint_id:\n"
        "blueprint:\n"
        f"created_at: {NOW}\n"
        "---\n"
        "\n"
        f"# {title}\n"
        "\n"
        "Conteúdo do roteiro de teste.\n",
        encoding="utf-8",
    )
    record = {
        "id": doc_id,
        "document_type": "video_script",
        "title": title,
        "path": str(path),
        "channel_id": "channel-1",
        "channel_name": "Canal Teste",
        "language": "pt",
        "blueprint_id": "",
        "blueprint_name": "",
        "created_at": NOW,
        "updated_at": "",
        "generation_settings": {},
    }
    storage.write_json("scripts.json", [record])
    return str(path)


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tasks: list[dict]) -> None:
    from hermes_ui import storage

    root = _isolate_storage(tmp_path, monkeypatch)
    storage.ensure_storage()
    storage.write_json("channels.json", [{"id": "channel-1", "name": "Canal Teste", "platform": "youtube", "active": True, "language": "pt"}])
    storage.write_json("tasks.json", tasks)
    storage.write_json("batches.json", [])
    doc_path = _write_script_document(root)
    # session_state fake: o sync guarda o fingerprint entre reruns.
    import app.main as app_main

    monkeypatch.setattr(app_main, "st", types.SimpleNamespace(session_state={}))
    return doc_path


def _run_sync() -> None:
    import app.main as app_main

    app_main._sync_saved_scripts_to_youtube_automation()


def _tasks() -> list[dict]:
    from hermes_ui import storage

    return storage.read_json("tasks.json", [])


def _pipeline_task(state: str, doc_path: str, *, with_document_id: bool) -> dict:
    task = {
        "id": f"video-{state}-1",
        "channel_id": "channel-1",
        "platform": "youtube",
        "state": state,
        "title": DOC_TITLE,
        "topic": DOC_TITLE,
        "topic_source": "llm",
        "stage": "upload" if state == "done" else "video",
        "progress": 100 if state == "done" else 52,
        "video_ready": state == "done",
        "artifacts": {"script": doc_path, **({"video": "C:/x.mp4"} if state == "done" else {})},
        "generation_settings": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    if with_document_id:
        task["artifacts"]["script_document_id"] = DOC_ID
    return task


# ── Cenários do relatório de bug ─────────────────────────────────────────────


def test_sync_does_not_create_task_when_done_pipeline_task_owns_script_by_artifact_path(tmp_path, monkeypatch):
    """Roteiro gerado por tarefa concluída (path no artefacto) não gera to_do."""
    doc_path = _prepare(tmp_path, monkeypatch, [])
    from hermes_ui import storage

    storage.write_json("tasks.json", [_pipeline_task("done", doc_path, with_document_id=False)])

    _run_sync()

    tasks = _tasks()
    assert len(tasks) == 1, "o sync criou uma tarefa duplicada para um roteiro com dona done"
    assert tasks[0]["id"] == "video-done-1"
    assert tasks[0]["state"] == "done"
    # A tarefa dona foi carimbada retroactivamente com o id do documento
    # (top-level — o artefacto continua a guardar o path, que alimenta o
    # fallback do índice em corridas futuras).
    assert tasks[0]["script_document_id"] == DOC_ID
    assert tasks[0]["artifacts"]["script"].endswith(f"-{DOC_ID}.md")


def test_sync_does_not_create_task_when_done_task_has_script_document_id(tmp_path, monkeypatch):
    """Dona com script_document_id carimbado (fluxo novo do pipeline) → sem duplicado."""
    doc_path = _prepare(tmp_path, monkeypatch, [])
    from hermes_ui import storage

    storage.write_json("tasks.json", [_pipeline_task("done", doc_path, with_document_id=True)])

    _run_sync()

    tasks = _tasks()
    assert len(tasks) == 1
    assert tasks[0]["state"] == "done"
    assert tasks[0]["script_document_id"] == DOC_ID


def test_sync_does_not_create_task_when_owner_failed(tmp_path, monkeypatch):
    """Tarefa dona failed: o roteiro não volta para o fim da fila — usa-se Refazer na original."""
    doc_path = _prepare(tmp_path, monkeypatch, [])
    from hermes_ui import storage

    storage.write_json("tasks.json", [_pipeline_task("failed", doc_path, with_document_id=False)])

    _run_sync()

    tasks = _tasks()
    assert len(tasks) == 1
    assert tasks[0]["state"] == "failed"


def test_sync_creates_task_for_genuinely_orphan_script(tmp_path, monkeypatch):
    """Feature preservada: roteiro sem NENHUMA dona continua a virar tarefa manual."""
    _prepare(tmp_path, monkeypatch, [])

    _run_sync()

    tasks = _tasks()
    assert len(tasks) == 1
    created = tasks[0]
    assert created["topic_source"] == "saved_script"
    assert created["script_document_id"] == DOC_ID
    assert created["manual_start_required"] is True
    assert created["state"] == "to_do"
    # Segunda passada: a partir de agora o documento tem dona — idempotente.
    _run_sync()
    assert len(_tasks()) == 1


# ── Helpers e carimbo do pipeline ─────────────────────────────────────────────


def test_script_document_id_from_artifact_extracts_id_from_real_filename(tmp_path, monkeypatch):
    import app.main as app_main

    extract = app_main._script_document_id_from_artifact
    assert extract("C:\\storage\\scripts\\roteiro-the-hidden-danger-e9fb8f3ee024.md") == DOC_ID
    assert extract("/storage/scripts/letra-morning-prayer-7e04254a5594.md") == "7e04254a5594"
    assert extract("") == ""
    assert extract("C:\\storage\\scripts\\sem-id.md") == ""
    assert extract("C:\\storage\\scripts\\roteiro-titulo-curto.md") == ""


def test_pipeline_stamps_script_document_id_artifact():
    """O pipeline carimba o id do documento no artefacto logo após o save."""
    assert 'artifacts["script"] = script_record.get("path", "")' in PIPELINE_SOURCE
    assert 'artifacts["script_document_id"] = str(script_record.get("id") or "")' in PIPELINE_SOURCE


def test_sync_indexes_pipeline_tasks_via_artifact_path_fallback():
    """Source assertion: o índice de donas extrai o id do path do artefacto."""
    main_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    block = main_source[main_source.index("def _sync_saved_scripts_to_youtube_automation("):main_source.index("def _automation_created_at(")]
    assert "document_id = _script_document_id_from_artifact(str(artifacts.get(\"script\") or existing.get(\"script_path\") or \"\"))" in block
    # O índice por id continua ANTES do filtro saved_script (tasks do pipeline entram).
    assert block.index('document_id = _script_document_id_from_artifact') < block.index('!= "saved_script":')
