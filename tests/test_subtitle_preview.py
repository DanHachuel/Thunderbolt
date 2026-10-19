from __future__ import annotations

from pathlib import Path

import pytest

from hermes_ui import text_to_images

ROOT = Path(__file__).resolve().parents[1]
APP_MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _test_font():
    for candidate in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(candidate).is_file():
            return candidate
    return None


def _config(**overrides):
    config = {
        "font_path": _test_font(),
        "font_size": 60,
        "position": "bottom",
        "color": "#FFFFFF",
        "background": True,
        "background_color": "#FF0000",
        "rounded": False,
        "outline": "#000000",
        "outline_width": 1.5,
    }
    config.update(overrides)
    return config


def _mask(frame, colour: tuple[int, int, int]):
    import numpy as np

    return (np.array(frame)[:, :, :3] == colour).all(axis=-1)


def _red_bbox(frame):
    import numpy as np

    mask = _mask(frame, (255, 0, 0))
    rows, cols = np.where(mask)
    assert rows.size, "o fundo da legenda (vermelho puro) não existe no frame"
    return int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max())


def test_preview_phrase_is_the_fixed_lorem_sentence():
    assert text_to_images.SUBTITLE_PREVIEW_PHRASE == "Lorem ipsum dolor sit amet consectetur adipiscing elit"


def test_subtitle_rgba_converts_real_colours_and_rejects_invalid():
    """1.0.09: regressão do bug em que TODAS as cores caíam no fallback.

    A validação antiga rejeitava sempre os canais (3 para RGB, 4 para RGBA),
    logo as cores escolhidas nas Configurações de legendas eram ignoradas na
    queima real — texto sempre branco, contorno e fundo sempre pretos.
    """
    assert text_to_images._subtitle_rgba("#FF0000", (1, 2, 3, 4)) == (255, 0, 0, 255)
    assert text_to_images._subtitle_rgba("#001A4A", (1, 2, 3, 4)) == (0, 26, 74, 255)
    assert text_to_images._subtitle_rgba("#abc", (1, 2, 3, 4)) == (170, 187, 204, 255)
    assert text_to_images._subtitle_rgba("#FF000080", (1, 2, 3, 4)) == (255, 0, 0, 128)
    assert text_to_images._subtitle_rgba("FF0000", (1, 2, 3, 4)) == (1, 2, 3, 4)
    assert text_to_images._subtitle_rgba("#GGGGGG", (1, 2, 3, 4)) == (1, 2, 3, 4)
    assert text_to_images._subtitle_rgba("", (1, 2, 3, 4)) == (1, 2, 3, 4)


@pytest.mark.skipif(_test_font() is None, reason="sem fonte do sistema")
def test_preview_frame_is_1080p_on_the_chosen_canvas_colour():
    frame = text_to_images.render_subtitle_preview_frame(_config(), canvas_color="#d3c4e3")
    assert frame.size == (1920, 1080)
    # canto superior esquerdo: cor do bloco de testes (lilás #d3c4e3)
    assert frame.getpixel((5, 5)) == (211, 196, 227)
    # a legenda existe: a caixa de fundo (vermelho puro) está presente
    _red_bbox(frame)


@pytest.mark.skipif(_test_font() is None, reason="sem fonte do sistema")
def test_preview_canvas_colour_changes_only_the_viewing_background():
    lilac = text_to_images.render_subtitle_preview_frame(_config(), canvas_color="#d3c4e3")
    navy = text_to_images.render_subtitle_preview_frame(_config(), canvas_color="#001A4A")
    assert lilac.getpixel((5, 5)) == (211, 196, 227)
    assert navy.getpixel((5, 5)) == (0, 26, 74)
    # a caixa da legenda fica exactamente no mesmo sítio nos dois fundos
    assert _red_bbox(lilac) == _red_bbox(navy)


@pytest.mark.skipif(_test_font() is None, reason="sem fonte do sistema")
def test_preview_position_top_center_and_bottom():
    """1.0.10: "top" desce e "bottom" sobe exactamente a altura do bloco — o
    respiro em cada borda equivale à altura da própria legenda; "center"
    continua centrado."""
    bottom = text_to_images.render_subtitle_preview_frame(_config(position="bottom"))
    top = text_to_images.render_subtitle_preview_frame(_config(position="top"))
    center = text_to_images.render_subtitle_preview_frame(_config(position="center"))
    # bottom: o bloco TERMINA a box_h pixels do fundo (sobe)
    _, top_b, _, bottom_b = _red_bbox(bottom)
    box_h = bottom_b - top_b + 1
    assert bottom_b + 1 + box_h == 1080  # gap inferior == altura do bloco
    assert top_b + 2 * box_h == 1080  # consistência: paste_y = video_h - 2*box_h
    # top: o bloco COMEÇA em box_h (desce) — gap superior == altura do bloco
    _, top_t, _, bottom_t = _red_bbox(top)
    box_h_top = bottom_t - top_t + 1
    assert top_t == box_h_top
    # center: mantém-se centrado
    _, top_c, _, _ = _red_bbox(center)
    assert 300 < top_c < 700


@pytest.mark.skipif(_test_font() is None, reason="sem fonte do sistema")
def test_montage_clips_use_the_same_dynamic_margin_as_the_preview():
    """WYSIWYG: a margem vertical dos clipes do vídeo real (MoviePy) segue a
    mesma matemática do Preview — ("center", y) com y = bloco (top) e
    y = video_h - 2*bloco (bottom); center inalterado."""
    from hermes_ui.text_to_images import _subtitle_clips_for_scenes

    scenes = [{"text": "Legenda de uma linha", "duration": 2.0}]
    bottom_clips = _subtitle_clips_for_scenes(scenes, 1920, 1080, _config(position="bottom"))
    assert len(bottom_clips) == 1
    block_h = int(bottom_clips[0].size[1])
    assert bottom_clips[0].pos(0) == ("center", 1080 - 2 * block_h)

    top_clips = _subtitle_clips_for_scenes(scenes, 1920, 1080, _config(position="top"))
    assert top_clips[0].pos(0) == ("center", int(top_clips[0].size[1]))

    center_clips = _subtitle_clips_for_scenes(scenes, 1920, 1080, _config(position="center"))
    assert center_clips[0].pos(0) == ("center", "center")

    # A margem acompanha a altura real do bloco: fontes maiores sobem/descem mais.
    big_clips = _subtitle_clips_for_scenes(scenes, 1920, 1080, _config(position="bottom", font_size=96))
    big_h = int(big_clips[0].size[1])
    assert big_h > block_h
    assert big_clips[0].pos(0) == ("center", 1080 - 2 * big_h)


@pytest.mark.skipif(_test_font() is None, reason="sem fonte do sistema")
def test_preview_rounded_background_cuts_the_box_corners_like_mpt():
    square = text_to_images.render_subtitle_preview_frame(_config(rounded=False))
    rounded = text_to_images.render_subtitle_preview_frame(_config(rounded=True))
    left, top, _, _ = _red_bbox(square)
    # quadrado: o canto superior esquerdo da caixa é fundo vermelho
    assert _mask(square, (255, 0, 0))[top, left]
    # arredondado: o mesmo canto é cortado — a cor do bloco de testes aparece
    assert not _mask(rounded, (255, 0, 0))[top, left]
    assert rounded.getpixel((left, top)) == (211, 196, 227)


@pytest.mark.skipif(_test_font() is None, reason="sem fonte do sistema")
def test_preview_without_background_has_no_box_only_text():
    frame = text_to_images.render_subtitle_preview_frame(_config(background=False))
    assert not _mask(frame, (255, 0, 0)).any()
    # mas o texto branco continua queimado no frame
    assert _mask(frame, (255, 255, 255)).any()


@pytest.mark.skipif(_test_font() is None, reason="sem fonte do sistema")
def test_preview_requires_a_resolved_font_path():
    with pytest.raises(ValueError):
        text_to_images.render_subtitle_preview_frame(_config(font_path=""))


def test_channel_card_uses_compact_grid_and_preview_block():
    """1.0.09: o bloco de legendas do card do canal é compacto e tem Preview.

    As chaves de estado e o payload de gravação ficam EXACTAMENTE iguais
    (restrição da tarefa) — o teste bloqueia regressões nas duas pontas.
    """
    block = APP_MAIN[APP_MAIN.index("def render_channel_audio_subtitle_defaults("):APP_MAIN.index("def render_channel_video_defaults(")]
    # grelha compacta em colunas (antes: st.columns(2) com empilhamento total)
    assert "style_cols = st.columns([2, 1.4, 1.2, 0.8])" in block
    assert "box_cols = st.columns([1.1, 0.7, 1.2, 1.1, 0.7])" in block
    # chaves de estado existentes inalteradas
    for key in (
        "channel_default_subtitles_{channel_id}",
        "channel_default_subtitle_font_{channel_id}",
        "channel_default_subtitle_position_{channel_id}",
        "channel_default_subtitle_color_{channel_id}",
        "channel_default_subtitle_background_{channel_id}",
        "channel_default_subtitle_background_color_{channel_id}",
        "channel_default_subtitle_rounded_background_{channel_id}",
        "channel_default_subtitle_font_size_{channel_id}",
        "channel_default_subtitle_outline_{channel_id}",
        "channel_default_subtitle_outline_width_{channel_id}",
        "save_channel_subtitle_defaults_{channel_id}",
    ):
        assert key in block, f"chave de estado perdida no redesign: {key}"
    # bloco de preview: fundo de teste customizável + botão Preview reativo
    assert 'st.color_picker("Cor de fundo do bloco de testes", value="#d3c4e3", key=f"channel_subtitle_preview_canvas_{channel_id}")' in block
    assert 'st.button("Preview", key=f"channel_subtitle_preview_{channel_id}")' in block
    assert "render_subtitle_preview_frame(" in block
    assert "SUBTITLE_PREVIEW_PHRASE" in block
    # payload de gravação no JSON do canal inalterado
    assert '"default_enable_subtitles": bool(enable_subtitles), "default_subtitle_font": selected_font' in block
    assert '"default_subtitle_outline_width": float(subtitle_outline_width)' in block
