from pathlib import Path

APP = Path("app/main.py").read_text(encoding="utf-8")


def test_youtube_automation_has_pipeline_and_posted_views_without_double_load():
    """0.9.95: st.tabs corria o corpo das DUAS sub-abas em cada rerun — o
    catálogo de tarefas era carregado e ordenado 2×. O selector segmentado
    só renderiza a vista activa: 1 leitura por rerun."""
    assert 'st.segmented_control(' in APP
    assert '["Pipeline", "Videos Postados"]' in APP
    assert 'posted_only=str(view or "Pipeline") != "Pipeline", tasks=tasks' in APP
    assert 'st.tabs(["Pipeline", "Videos Postados"])' not in APP


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
