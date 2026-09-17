from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_test_upload_youtube_destinations_use_canonical_platform_classifier():
    block = SOURCE.split("def _test_upload_destinations", 1)[1].split("def _render_test_upload_videos", 1)[0]
    assert '"Canais YouTube": "youtube"' in block
    assert "classify_channel_platform(item) == accepted_platform" in block
    assert "platform_map" not in block


def test_test_upload_videos_render_in_two_compact_columns():
    block = SOURCE.split("def _render_test_upload_videos", 1)[1].split("def ", 1)[0]
    assert "video_columns = st.columns(2, gap=\"small\")" in block
    assert "with video_columns[index]:" in block
    assert "_render_local_video_player(video_path)" in block


def test_vertical_test_video_uses_half_width_media_column():
    block = SOURCE.split("def _render_test_upload_videos", 1)[1].split("def ", 1)[0]
    assert 'video["id"] == "vertical"' in block
    assert 'st.columns([1, 2, 1])[1]' in block


def test_test_upload_button_is_between_selector_and_video_cards():
    block = SOURCE.split("def _render_test_upload_videos", 1)[1].split("def ", 1)[0]
    selector_position = block.index('key="test_upload_video"')
    button_position = block.index('key="test_upload_execute"')
    cards_position = block.index('video_columns = st.columns(2, gap="small")')
    assert selector_position < button_position < cards_position


def test_upload_status_panel_is_next_to_selector_and_before_button():
    block = SOURCE.split("def _render_test_upload_videos", 1)[1].split("def ", 1)[0]
    assert 'selector_column, status_column = st.columns([1, 1], gap="small")' in block
    assert 'with status_column:' in block
    assert 'st.container(height=188, border=True)' in block
    selector_position = block.index('key="test_upload_video"')
    button_position = block.index('key="test_upload_execute"')
    status_position = block.index('st.container(height=188, border=True)')
    cards_position = block.index('video_columns = st.columns(2, gap="small")')
    assert selector_position < status_position < button_position < cards_position


def test_test_video_options_remain_horizontal():
    block = SOURCE.split("def _render_test_upload_videos", 1)[1].split("def ", 1)[0]
    assert 'key="test_upload_video", horizontal=True' in block
