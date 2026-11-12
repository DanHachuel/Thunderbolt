from pathlib import Path


SOURCE = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")


def test_tiktok_has_pipeline_and_posted_tabs_with_closed_named_cards():
    block = SOURCE.split("def _render_tiktok_automation_cards():", 1)[1].split("def render_tiktok_automation():", 1)[0]
    assert 'st.tabs(["Pipeline", "Vídeos Postados"])' in block
    # 1.0.96 - M3: o catálogo é carregado UMA vez e partilhado pelas duas
    # sub-abas (antes cada uma relia tudo no mesmo ciclo de render).
    assert 'tiktok_tasks = load_automation_tasks_for_platform("tiktok")' in block
    assert "_render_tiktok_automation_task_list(tiktok_tasks, posted_only=False)" in block
    assert "_render_tiktok_automation_task_list(tiktok_tasks, posted_only=True)" in block
    assert block.count("load_automation_tasks_for_platform") == 1
    assert block.count('read_json("channels.json"') == 0


def test_youtube_shares_one_catalog_read_between_its_sub_tabs():
    """A variante YouTube é o modelo que a TikTok passou a seguir (1.0.96)."""
    block = SOURCE.split("def _render_youtube_automation_cards(", 1)[1].split("def _facebook_pages_for_automation", 1)[0]
    assert "_render_youtube_automation_task_list(posted_only=False, tasks=tasks)" in block
    assert "_render_youtube_automation_task_list(posted_only=True, tasks=tasks)" in block
    assert "load_automation_tasks_for_platform" not in block
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
