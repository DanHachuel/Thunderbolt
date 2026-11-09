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
    # Commit 85c26eb ("feat: separar pipeline e videos postados no youtube")
    # substituiu a secção "Vídeos cadastrados" por sub-abas Pipeline/Videos
    # Postados renderizadas por _render_youtube_automation_task_list.
    automation = source.split("def _render_youtube_automation_task_list", 1)[1].split("def _render_youtube_automation_cards", 1)[0]
    assert "thumbnail_path = _task_thumbnail_path(task)" in automation
    # 1.0.81: a thumbnail passou a ser renderizada por _render_task_thumbnail —
    # a imagem continua a vir do caminho (st.image faz stream), e quando não há
    # ficheiro aparece um placeholder em vez de um buraco branco.
    assert "_render_task_thumbnail(thumbnail_path)" in automation
    assert 'def _render_task_thumbnail(' in source
    assert 'st.image(str(thumbnail_path), width="stretch", caption="Thumbnail")' in source
    assert "Thumbnail não gerada" in source  # placeholder (nunca buraco branco)
    # o card do YouTube já não usa o caption antigo (outros renderizadores podem)
    card_body = source.split("def _youtube_task_card_body", 1)[1].split("@st.fragment", 1)[0]
    assert 'st.caption("Thumbnail ainda não pronta")' not in card_body
    assert "_render_task_thumbnail(thumbnail_path)" in card_body
    assert automation.index("_render_task_thumbnail(thumbnail_path)") < automation.index("with task_cols[1]:")


def test_thumbnail_renderers_reference_local_paths_instead_of_cached_bytes():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'st.image(_file_bytes(thumbnail_path)' not in source
    assert 'st.image(str(thumbnail_path), width="stretch", caption="Thumbnail")' in source
    assert 'st.image(_file_bytes(image_path)' not in source
    assert 'st.image(str(image_path), use_container_width=True)' in source
