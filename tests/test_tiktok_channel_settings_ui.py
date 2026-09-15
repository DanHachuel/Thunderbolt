from pathlib import Path


SOURCE = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")


def test_tiktok_forms_persist_voice_automation_and_time():
    block = SOURCE.split("def render_tiktok_channels():", 1)[1].split("def is_youtube_channel_record", 1)[0]
    assert '"default_voice": voice' in block
    assert '"automation_on": automation_on' in block
    assert '"automation_time": automation_time.strip()' in block
    assert 'valid_hhmm(automation_time)' in block


def test_tiktok_cards_show_requested_channel_settings():
    block = SOURCE.split("def render_tiktok_channels():", 1)[1].split("def is_youtube_channel_record", 1)[0]
    assert 'Narrador/Voz Padrão' in block
    assert 'Fonte do vídeo' in block
    assert 'Proporção do vídeo' in block
    assert 'tiktok_import_card_format_' not in block
    assert 'selectbox("Formato", CHANNEL_FORMAT_OPTIONS' not in block
    assert '"Nicho": "niche"' in block
    assert '"Horário diário (HH:MM)": "automation_time"' in block


def test_tiktok_cards_include_all_requested_actions_and_download_names():
    card_block = SOURCE.split("def _render_tiktok_automation_cards():", 1)[1].split("def render_tiktok_automation():", 1)[0]
    for label in ("Apagar", "Baixar Thumbnail 9:16", "Baixar Thumbnail Prompt", "Baixar Roteiro", "Baixar Vídeo9:16"):
        assert label in card_block
    assert '_automation_download_name("Thumbnail9:16", task, thumbnail_path, ".png")' in card_block
    assert '_automation_download_name("Thumbnail-Prompt", task, thumbnail_prompt_path, ".txt")' in card_block
    assert '_automation_download_name("Script", task, script_path, ".md")' in card_block
    assert '_automation_download_name("Vídeo9:16", task, video_path, ".mp4")' in card_block


def test_youtube_downloads_use_the_same_requested_name_patterns():
    card_block = SOURCE.split("def _render_youtube_automation_cards():", 1)[1].split("def render_automation():", 1)[0]
    assert SOURCE.split("def _render_youtube_automation_cards():", 1)[0].rstrip().endswith("@st.fragment(run_every=5.0)")
    assert '_automation_download_name("Thumbnail", task, thumbnail_path, ".png")' in card_block
    assert '_automation_download_name("Thumbnail-Prompt", task, thumbnail_prompt_path, ".txt")' in card_block
    assert '_automation_download_name("Script", task, script_path, ".md")' in card_block
    assert '_automation_download_name("Vídeo", task, video_path, ".mp4")' in card_block


def test_automation_download_title_uses_original_topic_without_losing_letters():
    name_block = SOURCE.split("def _download_title", 1)[1].split("def _automation_download_name", 1)[0]
    assert 'task.get("topic") or task.get("title")' in name_block
    assert 're.sub(r"\\s+", " ", cleaned)' in name_block
    assert 'return f"{prefix}_{_download_title(task)}{suffix}"' in SOURCE


def test_tiktok_automation_start_uses_shared_pipeline_start_helper():
    assert '@st.fragment(run_every=5.0)\ndef _render_tiktok_automation_cards()' in SOURCE
    assert 'key=f"tiktok_automation_start_{task_id}"' in SOURCE
    assert '_start_pipeline_task(task_id, state)' in SOURCE
    assert 'disabled=state not in {"to_do", "blocked", "failed"}' in SOURCE


def test_youtube_refresh_keeps_fragment_and_guards_script_sync():
    assert '@st.fragment(run_every=5.0)\ndef _render_youtube_automation_cards()' in SOURCE
    assert 'youtube_script_sync_signature' in SOURCE
    card_block = SOURCE.split("def _render_youtube_automation_cards():", 1)[1].split("def render_automation():", 1)[0]
    page_block = SOURCE.split("def render_automation():", 1)[1].split("def render_upload_direct():", 1)[0]
    assert "_sync_saved_scripts_to_youtube_automation()" not in card_block
    assert "_sync_saved_scripts_to_youtube_automation()" in page_block
