from pathlib import Path


def _isolated_storage(tmp_path):
    from hermes_ui import storage
    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.TIKTOK_PROMPT_MASTERS = storage.STORAGE / "tiktok" / "prompts_master"
    storage.ensure_storage()
    return storage


def test_create_video_now_for_channel_creates_one_pending_task_without_schedule(tmp_path):
    storage = _isolated_storage(tmp_path)
    channel = {
        "id": "channel-now",
        "name": "Canal imediato",
        "platform": "youtube",
        "active": True,
        "style_wide": "pexels",
        "language": "pt",
    }
    storage.write_json("channels.json", [channel])

    from hermes_ui.automation_worker import create_video_now_for_channel

    result = create_video_now_for_channel(channel)
    tasks = storage.read_json("tasks.json", [])
    batches = storage.read_json("batches.json", [])

    assert len(result["tasks"]) == 1
    assert len(tasks) == 1
    assert tasks[0]["channel_id"] == "channel-now"
    assert tasks[0]["state"] == "to_do"
    assert tasks[0].get("manual_start_required", False) is False
    assert len(batches) == 1
    assert batches[0]["options"]["manual_create"] is True


def test_automation_ui_has_create_video_and_log_download_column():
    source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert 'st.button("Criar Vídeo", key=f"youtube_automation_create_video_{channel_id}"' in source
    assert 'st.button("Criar Vídeo", key=f"tiktok_automation_create_video_{channel_id}"' in source
    assert 'file_name=log_download[1] if log_download else "run-codigo.md"' in source
    assert 'log_columns = ["Download", "Operação"' in source
    assert "create_video_now_for_channel" in source
