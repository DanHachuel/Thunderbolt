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
    # 1.0.96 - M4: o caminho continua a ir directo para o st.image (nunca
    # bytes em cache), mas passa primeiro pela miniatura reduzida.
    assert 'st.image(str(_thumbnail_display_path(thumbnail_path)), width="stretch", caption="Thumbnail")' in source
    assert "Thumbnail não gerada" in source  # placeholder (nunca buraco branco)
    # o card do YouTube já não usa o caption antigo (outros renderizadores podem)
    card_body = source.split("def _youtube_task_card_body", 1)[1].split("@st.fragment", 1)[0]
    assert 'st.caption("Thumbnail ainda não pronta")' not in card_body
    assert "_render_task_thumbnail(thumbnail_path)" in card_body
    assert automation.index("_render_task_thumbnail(thumbnail_path)") < automation.index("with task_cols[1]:")


def test_thumbnail_renderers_reference_local_paths_instead_of_cached_bytes():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'st.image(_file_bytes(thumbnail_path)' not in source
    # 1.0.96 - M4: continua a ser um CAMINHO local (nunca bytes), mas passa
    # pela miniatura reduzida em cache antes de ir para o browser.
    assert 'st.image(str(_thumbnail_display_path(thumbnail_path)), width="stretch", caption="Thumbnail")' in source
    assert "def _thumbnail_display_path(" in source
    assert "_THUMBNAIL_DISPLAY_WIDTH" in source
    assert 'st.image(_file_bytes(image_path)' not in source
    assert 'st.image(str(image_path), use_container_width=True)' in source


def test_thumbnail_display_path_reduces_and_caches_big_thumbnails(tmp_path, monkeypatch):
    """Prova funcional: uma thumbnail grande dá uma miniatura pequena em cache."""
    from PIL import Image

    monkeypatch.setattr(main_module := __import__("app.main", fromlist=["x"]), "_THUMBNAIL_CACHE_DIR", tmp_path / "cache")
    original = tmp_path / "thumb.png"
    # ruído aleatório: um PNG sólido comprimiria para poucos KB e não provaria
    # nada sobre a redução — o que interessa aqui é a LARGURA.
    Image.effect_noise((1280, 720), 90).convert("RGB").save(original, format="PNG")
    assert original.stat().st_size > 20_000

    miniatura = main_module._thumbnail_display_path(original)
    assert miniatura != original
    assert miniatura.is_file()
    with Image.open(miniatura) as imagem:
        assert imagem.width == 360
        assert imagem.height == 202
    # segunda chamada: a miniatura é REAPROVEITADA (nenhuma nova codificação)
    conteudo = miniatura.read_bytes()
    assert main_module._thumbnail_display_path(original) == miniatura
    assert miniatura.read_bytes() == conteudo


def test_thumbnail_display_path_never_breaks_on_a_bad_file(tmp_path, monkeypatch):
    """Falha na redução devolve o ORIGINAL — o card continua a mostrar a imagem."""
    monkeypatch.setattr(main_module := __import__("app.main", fromlist=["x"]), "_THUMBNAIL_CACHE_DIR", tmp_path / "cache")
    corrompido = tmp_path / "corrompido.png"
    corrompido.write_bytes(b"isto nao e uma imagem")
    assert main_module._thumbnail_display_path(corrompido) == corrompido


def test_thumbnail_display_path_keeps_small_images_untouched_in_size(tmp_path, monkeypatch):
    """Uma imagem já pequena não é reduzida (e o cache nasce na mesma)."""
    from PIL import Image

    monkeypatch.setattr(main_module := __import__("app.main", fromlist=["x"]), "_THUMBNAIL_CACHE_DIR", tmp_path / "cache")
    pequena = tmp_path / "small.png"
    Image.new("RGB", (240, 135), (10, 10, 10)).save(pequena, format="PNG")
    miniatura = main_module._thumbnail_display_path(pequena)
    with Image.open(miniatura) as imagem:
        assert imagem.width == 240
