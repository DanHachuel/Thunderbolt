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
    assert 'st.video(str(video_path), width="stretch")' in block
