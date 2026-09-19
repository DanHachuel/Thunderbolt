from pathlib import Path

from app.main import _task_thumbnail_path


def test_task_thumbnail_path_resolves_existing_artifact(tmp_path):
    thumbnail = tmp_path / "thumb.png"
    thumbnail.write_bytes(b"png")
    task = {"artifacts": {"thumbnail": str(thumbnail)}}
    assert _task_thumbnail_path(task) == thumbnail


def test_task_thumbnail_path_uses_legacy_cover_field(tmp_path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"jpg")
    task = {"artifacts": {"cover": str(cover)}}
    assert _task_thumbnail_path(task) == cover


def test_automation_cards_render_thumbnail_before_video_metadata():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    automation = source.split('st.subheader("Vídeos cadastrados")', 1)[1].split("def render_upload_direct", 1)[0]
    assert "thumbnail_path = _task_thumbnail_path(task)" in automation
    assert 'st.image(str(thumbnail_path), width=180, caption="Thumbnail")' in automation
    assert 'st.caption("Thumbnail ainda não pronta")' in automation


def test_thumbnail_renderers_reference_local_paths_instead_of_cached_bytes():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'st.image(_file_bytes(thumbnail_path)' not in source
    assert 'st.image(str(thumbnail_path), width=180, caption="Thumbnail")' in source
    assert 'st.image(_file_bytes(image_path)' not in source
    assert 'st.image(str(image_path), use_container_width=True)' in source
