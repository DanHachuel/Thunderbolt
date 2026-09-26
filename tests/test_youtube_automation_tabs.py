from pathlib import Path

APP = Path("app/main.py").read_text(encoding="utf-8")


def test_youtube_automation_has_pipeline_and_posted_tabs():
    assert 'st.tabs(["Pipeline", "Videos Postados"])' in APP
    assert '_render_youtube_automation_task_list(posted_only=False)' in APP
    assert '_render_youtube_automation_task_list(posted_only=True)' in APP


def test_youtube_queue_items_are_collapsed_with_only_title_and_channel_header():
    assert 'with st.expander(f"{task_title} · {task_channel}", expanded=False):' in APP
    assert 'task_title = str(task.get("topic") or task.get("title")' in APP
    assert 'task_channel = str(task.get("channel_name")' in APP


def test_posted_classification_requires_remote_confirmation_or_manual_upload_ok():
    assert "def _youtube_task_is_posted" in APP
    assert "remote_reference" in APP
    assert "manual_confirmation" in APP
    assert 'status in {"published", "success", "successful", "done", "completed"}' in APP


def test_pipeline_and_posted_views_are_partitioned():
    assert 'tasks = [task for task in all_tasks if _youtube_task_is_posted(task) is posted_only]' in APP
    assert 'st.subheader("Videos Postados" if posted_only else "Pipeline")' in APP
