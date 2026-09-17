from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_backlog_defaults_to_done_filter_and_normalizes_state():
    block = SOURCE.split("def render_videos():", 1)[1].split("def _music_backlog_records", 1)[0]
    assert 'st.session_state["videos_state_filter"] = "done"' in block
    assert 'task_state = _catalog_task_state(task)' in block
    assert 'str(state_filter).strip().casefold()' in block


def test_catalog_reads_both_storage_locations_and_legacy_fields():
    block = SOURCE.split("def load_video_tasks_for_catalog() -> list[dict[str, Any]]:", 1)[1].split("def task_platform", 1)[0]
    assert 'legacy_path = STORAGE / "tasks.json"' in block
    assert '"video_path", "output_video", "video_file", "video"' in block
    assert 'task.get("task_id")' in block
    assert 'legacy-{hashlib.sha1(identity.encode(\'utf-8\')).hexdigest()[:16]}' in block


def test_done_cards_keep_player_and_download():
    block = SOURCE.split("def render_videos():", 1)[1].split("def _music_backlog_records", 1)[0]
    assert 'task_state == "done"' in block
    assert '_render_local_video_player(video_file, width=360)' in block
    assert "pipeline_video_download_" in block
