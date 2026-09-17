"""Contracts for the shared video catalog and automation card state display."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_backlog_and_automation_use_the_same_complete_task_catalog():
    assert "def load_video_tasks_for_catalog()" in MAIN_SOURCE
    assert MAIN_SOURCE.count("tasks = load_video_tasks_for_catalog()") >= 2
    assert "Return the complete persisted task catalog shared by Backlog and Automation" in MAIN_SOURCE


def test_automation_video_cards_show_state_progress_and_format_like_backlog():
    assert MAIN_SOURCE.count("_render_video_task_state(task)") >= 2
    assert MAIN_SOURCE.count("_video_task_format(task)") >= 2
    for state in ("to_do", "doing", "blocked", "done", "failed", "cancelled"):
        assert f'"{state}":' in MAIN_SOURCE
    assert 'st.progress(progress, text=f"{progress}%")' in MAIN_SOURCE
    assert 'st.caption("Formato")' in MAIN_SOURCE
    assert 'value = task.get("format") or task.get("style_wide") or task.get("style") or "wide"' in MAIN_SOURCE


def test_backlog_includes_extra_states_instead_of_dropping_them_from_the_filter():
    assert 'extra_states = sorted({str(task.get("state") or "unknown")' in MAIN_SOURCE
    assert 'state_filter = st.selectbox("Filtrar por estado", ["Todos", *known_states, *extra_states]' in MAIN_SOURCE


def test_backlog_starts_with_all_states_and_does_not_surface_upload_failure():
    assert 'st.session_state["videos_state_filter"] = "Todos"' in MAIN_SOURCE
    assert 'if video_path is not None and (bool(task.get("video_ready"))' in MAIN_SOURCE
    assert '_render_video_task_state(task, state_override=task_state)' in MAIN_SOURCE
    assert 'stage_task = {**task, "stage": "video"}' in MAIN_SOURCE
    assert 'state = task_state' in MAIN_SOURCE


def test_backlog_player_uses_resolved_video_artifact_path():
    assert 'video_file = _task_artifact_path(task, "video")' in MAIN_SOURCE
    assert 'if video_file is not None and task_state == "done":' in MAIN_SOURCE
    assert 'st.video(str(video_file), width=360)' in MAIN_SOURCE
    backlog_block = MAIN_SOURCE.split("def render_videos():", 1)[1].split("def _music_backlog_records", 1)[0]
    assert 'with video_file.open("rb") as video_stream:' in backlog_block
    assert "data=video_file.read_bytes()" not in backlog_block


def test_youtube_automation_cards_refresh_periodically_without_global_refresh():
    block = MAIN_SOURCE.split("@st.fragment(run_every=5.0)\ndef _render_youtube_automation_cards():", 1)[1].split("def _facebook_pages_for_automation", 1)[0]
    assert '@st.fragment(run_every=5.0)\ndef _render_youtube_automation_cards():' in MAIN_SOURCE
    assert 'tasks = load_automation_tasks_for_platform("youtube")' in block
    assert 'st.rerun()' not in block
    assert 'st.rerun(scope="fragment")' in block


def test_facebook_automation_keeps_periodic_refresh_contract():
    assert '@st.fragment(run_every=5.0)\ndef _render_facebook_automation_cards()' in MAIN_SOURCE
