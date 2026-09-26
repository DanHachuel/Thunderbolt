from pathlib import Path


SOURCE = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")


def test_tiktok_has_pipeline_and_posted_tabs_with_closed_named_cards():
    block = SOURCE.split("def _render_tiktok_automation_cards():", 1)[1].split("def render_tiktok_automation():", 1)[0]
    assert 'st.tabs(["Pipeline", "Vídeos Postados"])' in block
    assert '_render_tiktok_automation_task_list(posted_only=False)' in block
    assert '_render_tiktok_automation_task_list(posted_only=True)' in block
    assert 'with st.expander(f"{task_title} · {task_channel}", expanded=False)' in SOURCE
    assert '_automation_task_is_posted(task) is posted_only' in SOURCE


def test_bilibili_has_pipeline_and_posted_tabs_with_closed_named_cards():
    block = SOURCE.split("def _render_bilibili_automation_cards", 1)[1].split("def render_bilibili_automation", 1)[0]
    assert 'st.tabs(["Pipeline", "Vídeos Postados"])' in block
    assert '_render_bilibili_automation_task_card(task)' in block
    assert 'with st.expander(label, expanded=False)' in SOURCE
    assert 'load_automation_tasks_for_platform("bilibili")' in block


def test_music_automation_is_wired_and_has_two_tabs_with_closed_cards():
    assert '"Automação Musicas": render_music_automation' in SOURCE
    block = SOURCE.split("def render_music_automation()", 1)[1].split("def render_music_upload", 1)[0]
    assert 'st.tabs(["Pipeline", "Vídeos Postados"])' in block
    assert 'with st.expander(f"{title} · {channel}", expanded=False)' in SOURCE
    assert '_music_backlog_records()' in block
    assert '_music_upload_records()' in block
