"""Contracts for the shared video catalog and automation card state display."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_backlog_and_automation_use_the_same_complete_task_catalog():
    assert "def load_video_tasks_for_catalog()" in MAIN_SOURCE
    assert MAIN_SOURCE.count("tasks = load_video_tasks_for_catalog()") >= 2
    assert "Return the complete persisted task catalog shared by Backlog and Automation" in MAIN_SOURCE


def test_automation_video_cards_show_state_progress_and_video_source_like_backlog():
    assert MAIN_SOURCE.count("_render_video_task_state(task)") >= 2
    assert MAIN_SOURCE.count("_video_task_format(task)") >= 1
    for state in ("to_do", "doing", "blocked", "done", "failed", "cancelled"):
        assert f'"{state}":' in MAIN_SOURCE
    assert 'st.progress(progress, text=f"{progress}%")' in MAIN_SOURCE
    assert 'st.caption("Fonte do vídeo")' in MAIN_SOURCE
    assert 'value = task.get("format") or task.get("style_wide") or task.get("style") or "wide"' in MAIN_SOURCE
    assert "def _video_task_source(task: dict[str, Any]) -> str:" in MAIN_SOURCE


def test_youtube_automation_loads_local_video_player_only_after_explicit_request():
    block = MAIN_SOURCE.split("def _render_youtube_automation_task_list", 1)[1].split("def _facebook_pages_for_automation", 1)[0]
    assert '_render_local_video_player(video_path, width="stretch")' in block
    assert 'if video_path is not None and _catalog_task_state(task) == "done":' in block
    assert 'st.button("Reproduzir vídeo"' in block
    assert 'player_state_key = "youtube_automation_player_task_id"' in block
    player_block = block.split('if st.session_state.get(player_state_key) == player_task_id:', 1)[1].split('elif st.button("Reproduzir vídeo"', 1)[0]
    assert '_render_local_video_player(video_path, width="stretch")' in player_block


def test_youtube_automation_video_download_uses_static_link_and_defers_fallback_payload():
    assert 'def _local_video_download_link(path: Path, filename: str) -> str | None:' in MAIN_SOURCE
    assert 'def _clear_youtube_automation_download_task() -> None:' in MAIN_SOURCE
    block = MAIN_SOURCE.split('with video_download_col:', 1)[1].split('if st.button(\n                        "Upload"', 1)[0]
    assert '_local_video_download_link(video_path, download_name)' in block
    assert 'download_task_key = "youtube_automation_download_task_id"' in block
    assert 'if st.session_state.get(download_task_key) == task_id:' in block
    assert 'data=video_stream' in block
    assert 'on_click=_clear_youtube_automation_download_task' in block


def test_legacy_ready_artifacts_are_displayed_as_fully_complete():
    assert 'progress = max(0, min(100, int(task.get("progress") or 0)))' in MAIN_SOURCE
    assert 'if progress < 100 and _task_artifact_path(task, "video") is not None and _task_thumbnail_path(task) is not None:' in MAIN_SOURCE
    assert "return 100" in MAIN_SOURCE.split("def _video_task_progress", 1)[1].split("def _render_video_task_state", 1)[0]


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
    assert '_render_local_video_player(video_file, width="stretch")' in MAIN_SOURCE
    backlog_block = MAIN_SOURCE.split("def render_videos():", 1)[1].split("def _music_backlog_records", 1)[0]
    assert 'with video_file.open("rb") as video_stream:' in backlog_block
    assert "data=video_file.read_bytes()" not in backlog_block


def test_youtube_automation_cards_do_not_poll_each_browser_session():
    block = MAIN_SOURCE.split("@st.fragment\ndef _render_youtube_automation_cards():", 1)[1].split("def _facebook_pages_for_automation", 1)[0]
    assert '@st.fragment\ndef _render_youtube_automation_cards():' in MAIN_SOURCE
    assert '@st.fragment(run_every=5.0)\ndef _render_youtube_automation_cards():' not in MAIN_SOURCE
    assert 'tasks = load_automation_tasks_for_platform("youtube")' in MAIN_SOURCE
    assert 'st.rerun()' not in block
    assert 'st.rerun(scope="fragment")' in MAIN_SOURCE


def test_facebook_automation_does_not_poll_each_browser_session():
    assert '@st.fragment\ndef _render_facebook_automation_cards()' in MAIN_SOURCE
    assert '@st.fragment(run_every=5.0)\ndef _render_facebook_automation_cards()' not in MAIN_SOURCE
