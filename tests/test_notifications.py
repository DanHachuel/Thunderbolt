from pathlib import Path


def _isolated_storage(tmp_path):
    from hermes_ui import storage

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.TIKTOK_PROMPT_MASTERS = storage.STORAGE / "tiktok" / "prompts_master"
    storage.ensure_storage()
    return storage


def test_catalog_and_preferences_cover_each_operation(tmp_path):
    storage = _isolated_storage(tmp_path / "catalog")
    from hermes_ui import notifications

    catalog = notifications.notification_event_catalog()
    preferences = notifications.notification_preferences()
    assert len(catalog) >= 20
    assert {item["code"] for item in catalog} == set(preferences)
    assert all(preferences.values())
    saved = notifications.save_notification_preferences({"video_completed": False})
    assert saved["video_completed"] is False
    assert saved["music_completed"] is True
    assert storage.read_json("settings.json", {})["notification_preferences"]["video_completed"] is False


def test_disabled_event_is_not_written_and_duplicate_is_ignored(tmp_path):
    _isolated_storage(tmp_path / "disabled")
    from hermes_ui import notifications

    notifications.save_notification_preferences({"video_completed": False})
    assert notifications.record_notification("video_completed", "Vídeo", "Não deve aparecer", dedupe_key="task:one") is None
    notifications.save_notification_preferences({"video_completed": True})
    first = notifications.record_notification("video_completed", "Vídeo", "Concluído", dedupe_key="task:one")
    duplicate = notifications.record_notification("video_completed", "Vídeo", "Concluído novamente", dedupe_key="task:one")
    assert first is not None
    assert duplicate is None
    assert len(notifications.list_notifications()) == 1


def test_transition_task_creates_final_notification_once(tmp_path):
    storage = _isolated_storage(tmp_path / "transition")
    from hermes_ui.domain import transition_task
    from hermes_ui.notifications import list_notifications

    storage.write_json("tasks.json", [{"id": "video-1", "state": "doing", "stage": "video", "title": "Vídeo teste", "channel_name": "Canal teste", "music_mode": False, "artifacts": {}}])
    updated = transition_task("video-1", "done")
    assert updated["state"] == "done"
    entries = list_notifications()
    assert len(entries) == 1
    assert entries[0]["event_type"] == "video_completed"
    transition_task("video-1", "done")
    assert len(list_notifications()) == 1


def test_failed_task_notification_includes_api_attribution(tmp_path):
    storage = _isolated_storage(tmp_path / "failed-api")
    from hermes_ui.domain import transition_task
    from hermes_ui.notifications import list_notifications

    storage.write_json("tasks.json", [{
        "id": "video-api-failure",
        "state": "doing",
        "stage": "video",
        "title": "Vídeo com erro de API",
        "channel_name": "Canal",
        "error": "Credencial rejeitada",
        "failure_api": "Pixabay API",
        "failure_provider": "pixabay",
        "failure_service": "MoneyPrinterTurbo",
        "failure_config_fields": "pixabay_api_keys",
        "artifacts": {},
    }])

    transition_task("video-api-failure", "failed", error="Credencial rejeitada")

    entry = list_notifications()[0]
    assert entry["event_type"] == "activity_failed"
    assert entry["metadata"]["failure_api"] == "Pixabay API"
    assert "API/provider: Pixabay API" in entry["message"]
    assert entry["metadata"]["failure_provider"] == "pixabay"
    assert entry["metadata"]["failure_config_fields"] == "pixabay_api_keys"


def test_music_and_script_reconciliation_are_separate(tmp_path):
    storage = _isolated_storage(tmp_path / "music-script")
    from hermes_ui.notifications import list_notifications, reconcile_persisted_notifications

    storage.write_json("tasks.json", [
        {"id": "music-1", "state": "done", "stage": "video", "title": "Música teste", "channel_name": "Canal", "music_mode": True, "artifacts": {}},
        {"id": "script-task-1", "state": "done", "stage": "script", "title": "Roteiro teste", "channel_name": "Documento independente", "music_mode": False, "artifacts": {}},
    ])
    storage.write_json("scripts.json", [{"id": "script-1", "title": "Roteiro independente", "document_type": "video_script"}, {"id": "lyrics-1", "title": "Letra", "document_type": "music_lyrics"}])
    created = reconcile_persisted_notifications()
    assert created == 4
    event_types = {item["event_type"] for item in list_notifications()}
    assert {"music_completed", "script_stage_completed", "standalone_script_generated", "music_lyrics_generated"} <= event_types
    assert reconcile_persisted_notifications() == 0


def test_upload_automation_and_sensitive_metadata_are_safe(tmp_path):
    storage = _isolated_storage(tmp_path / "upload-automation")
    from hermes_ui.notifications import list_notifications, reconcile_persisted_notifications, record_notification

    storage.write_json("uploads.json", [{"id": "upload-1", "task_id": "task-1", "destination": "TikTok", "status": "published", "target": {"name": "Conta TikTok", "username": "@conta"}, "data": {"route": "tiktok_api", "access_token": "secret"}, "created_at": "2026-08-22T12:00:00+00:00"}])
    storage.write_json("automation_worker.json", {"last_runs": {"channel-1": {"batch_id": "batch-1", "time": "12:00"}}})
    record_notification("upload_tiktok_success", "Upload concluído", "Bearer abc", metadata={"access_token": "secret", "target": {"name": "Conta"}}, dedupe_key="manual-sensitive")
    reconcile_persisted_notifications()
    entries = list_notifications()
    assert {item["event_type"] for item in entries} >= {"upload_tiktok_success", "automation_completed"}
    serialized = str(entries)
    assert "secret" not in serialized
    assert "Bearer abc" not in serialized


def test_upload_post_success_is_reconciled_to_its_own_event(tmp_path):
    storage = _isolated_storage(tmp_path / "upload-post")
    from hermes_ui.notifications import list_notifications, reconcile_persisted_notifications

    storage.write_json("uploads.json", [{
        "id": "upload-post-1",
        "task_id": "task-1",
        "destination": "Upload-Post",
        "status": "published",
        "target": {"username": "profile", "platforms": ["tiktok", "instagram"]},
        "data": {"request_id": "request-1"},
        "created_at": "2026-08-22T12:00:00+00:00",
    }])
    assert reconcile_persisted_notifications() == 1
    entries = list_notifications()
    assert entries[0]["event_type"] == "upload_upload_post_success"
    assert entries[0]["metadata"]["destination"] == "Upload-Post"


def test_notification_actions_manage_read_state_and_history(tmp_path):
    _isolated_storage(tmp_path / "actions")
    from hermes_ui import notifications

    first = notifications.record_notification("automation_completed", "Automação", "Concluída", dedupe_key="automation:1")
    second = notifications.record_notification("cuts_completed", "Cortes", "Concluídos", dedupe_key="cuts:1")
    assert notifications.unread_notification_count() == 2
    assert notifications.mark_notification_read(first["id"])
    assert notifications.unread_notification_count() == 1
    assert notifications.mark_all_notifications_read() == 1
    assert notifications.unread_notification_count() == 0
    assert notifications.clear_notifications() == 2
    assert notifications.list_notifications() == []


def test_notifications_page_exposes_all_controls():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "main.py").read_text(encoding="utf-8")
    for label in ("Operações notificadas", "Guardar preferências", "Marcar todas como lidas", "Actualizar notificações", "Limpar histórico", "Histórico de notificações"):
        assert label in source
    assert "notification_event_catalog()" in source
    assert "notification_preference_" in source
    assert "reconcile_persisted_notifications()" in source


def test_notifications_page_reads_only_five_recent_entries():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "main.py").read_text(encoding="utf-8")
    start = source.index("def render_notifications():")
    end = source.index("def render_models_ai_tutorial():", start)
    block = source[start:end]
    assert "list_notifications(limit=5)" in block
    assert "list_notifications(limit=5, category=category_filter, unread_only=unread_filter)" in block
    assert "list_notifications(limit=500" not in block
    assert "list_notifications(limit=500" not in source


def test_notification_reconciliation_is_session_file_sensitive():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "main.py").read_text(encoding="utf-8")
    assert "_notification_reconciliation_signature" in source
    assert "_NOTIFICATION_RECONCILIATION_FILES" in source
    assert "reconcile_persisted_notifications(force=True)" in source


def test_notified_operations_are_inside_a_closed_expander():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "main.py").read_text(encoding="utf-8")
    start = source.index('with st.expander("Operações notificadas", expanded=False):')
    end = source.index('st.subheader("Histórico de notificações")', start)
    block = source[start:end]
    assert 'st.form("notification_preferences_form")' in block
    assert 'st.form_submit_button("Guardar preferências"' in block


def test_worker_and_music_storage_emit_completion_events(tmp_path):
    storage = _isolated_storage(tmp_path / "worker-music")
    from datetime import datetime
    from hermes_ui import automation_worker
    from hermes_ui.music import store_music_file
    from hermes_ui.notifications import list_notifications

    current = datetime.now().astimezone().replace(hour=12, minute=34, second=0, microsecond=0)
    storage.write_json("channels.json", [{"id": "channel-1", "name": "Canal automático", "active": True, "automation_on": True, "automation_time": "12:34", "daily_limit": 1, "language": "Português", "style_wide": "pexels"}])
    original_payload = automation_worker._creative_payload
    automation_worker._creative_payload = lambda channel: ("Tema automático", {"topic": "Tema automático", "title": "Vídeo automático"})
    try:
        result = automation_worker.run_once(current)
    finally:
        automation_worker._creative_payload = original_payload
    assert result["ok"] is True
    assert result["created"]
    music_path = store_music_file("faixa-teste.mp3", b"audio")
    assert music_path.is_file()
    event_types = {item["event_type"] for item in list_notifications()}
    assert {"automation_completed", "music_completed"} <= event_types
