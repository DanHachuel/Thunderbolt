from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_backlog_defaults_to_done_filter():
    block = SOURCE.split("def render_videos():", 1)[1].split("def _music_backlog_records", 1)[0]
    assert 'st.session_state["videos_state_filter"] = "done"' in block
    assert 'key="videos_state_filter"' in block


def test_done_backlog_uses_compact_native_video_player():
    block = SOURCE.split("def render_videos():", 1)[1].split("def _music_backlog_records", 1)[0]
    assert 'cols = st.columns([2.2, 2.2, 1, 1, 1.2, 1.8])' in block
    assert 'task_state == "done"' in block
    assert 'st.video(str(video_file), width=360)' in block
    assert "pipeline_video_download_" in block


def test_done_filter_normalizes_persisted_state_values():
    assert "def _catalog_task_state(task: dict[str, Any]) -> str:" in SOURCE
    block = SOURCE.split("def render_videos():", 1)[1].split("def _music_backlog_records", 1)[0]
    assert "task_state = _catalog_task_state(task)" in block
    assert "str(state_filter).strip().casefold()" in block


def test_catalog_keeps_legacy_ready_video_records_without_id():
    block = SOURCE.split("def load_video_tasks_for_catalog() -> list[dict[str, Any]]:", 1)[1].split("def task_platform", 1)[0]
    assert 'task.get("task_id")' in block
    assert '"video_path", "output_video", "video_file"' in block
    assert 'task.get("video")' in block
    assert 'legacy-{hashlib.sha1(identity.encode(\'utf-8\')).hexdigest()[:16]}' in block


def test_empty_destinations_do_not_gate_backlog_rendering():
    block = SOURCE.split("def render_videos():", 1)[1].split("def _music_backlog_records", 1)[0]
    assert "channels" not in block
    assert "Cadastre primeiro" not in block
