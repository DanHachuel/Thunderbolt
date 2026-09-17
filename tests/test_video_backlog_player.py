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
    assert 'str(task.get("state") or "").casefold() == "done"' in block
    assert 'st.video(video_file.read_bytes(), width=360)' in block
    assert "pipeline_video_download_" in block


def test_empty_destinations_do_not_gate_backlog_rendering():
    block = SOURCE.split("def render_videos():", 1)[1].split("def _music_backlog_records", 1)[0]
    assert "channels" not in block
    assert "Cadastre primeiro" not in block
