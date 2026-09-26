from pathlib import Path


APP = Path("app/main.py").read_text(encoding="utf-8")


def test_youtube_automation_has_pipeline_and_posted_tabs():
    assert 'st.tabs(["Pipeline", "Videos Postados"])' in APP
    assert 'with pipeline_tab:' in APP
    assert 'with posted_tab:' in APP


def test_youtube_queue_items_are_collapsed_by_default():
    assert 'st.expander(f"{task_title} · {task_channel}", expanded=False)' in APP
    assert 'task.get("channel_name")' in APP


def test_posted_tasks_require_confirmed_remote_upload():
    assert "def _youtube_task_is_posted" in APP
    assert "has_remote_reference" in APP
    assert 'status in {"published", "success", "successful", "done", "completed"}' in APP


def test_pipeline_excludes_posted_and_posted_view_includes_only_posted():
    assert 'tasks = [task for task in all_tasks if _youtube_task_is_posted(task) is posted_only]' in APP
    assert 'st.subheader("Videos Postados" if posted_only else "Pipeline")' in APP


def test_task_header_does_not_show_details_before_opening():
    assert 'st.caption(f"ID da tarefa: {task.get(\'id\', \'\')}")' in APP
    assert 'expanded=False' in APP
