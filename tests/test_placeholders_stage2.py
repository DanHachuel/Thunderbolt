from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_google_images_source_is_available_but_music_clips_remain_unavailable():
    # 0.9.52: o Remotion deixou de ser placeholder — a fonte está activa e
    # gated pelo ambiente (get_remotion_status); só os Clipes de Música
    # permanecem indisponíveis.
    assert 'UNAVAILABLE_VIDEO_SOURCES = {"music_clips"}' in MAIN_SOURCE
    assert 'channel_video_source_storage(wide_style_label) == "google_images"' in MAIN_SOURCE
    assert 'style in UNAVAILABLE_VIDEO_SOURCES' in MAIN_SOURCE


def test_remotion_source_is_gated_by_environment_status():
    assert 'if style == "remotion":' in MAIN_SOURCE
    assert "_remotion_availability()" in MAIN_SOURCE
    assert 'remotion_availability.get("available")' in MAIN_SOURCE
    assert "from hermes_ui.remotion_provider import get_remotion_status" in MAIN_SOURCE
    # O guard de instância única exclui os renders Remotion activos.
    kill_tree_source = (ROOT / "scripts" / "kill_tree.py").read_text(encoding="utf-8")
    assert 'REMOTION_RENDER_MARKER = "--thunderbolt-role=remotion-render"' in kill_tree_source
    assert "if REMOTION_RENDER_MARKER in cmdline:" in kill_tree_source


def test_google_images_card_has_settings_actions():
    # Bloco da função do pool de web images (a332304).
    start = MAIN_SOURCE.index("def render_web_images_cards(")
    end = MAIN_SOURCE.index("\ndef ", start + 1)
    block = MAIN_SOURCE[start:end]
    assert "Adicionar fornecedor" in block
    assert "Testar chamada API" in block
    assert "Salvar" in block
    assert "Remover card" in block
    assert "web_images_cards" in block


def test_google_images_copyright_warning_is_present():
    assert "GOOGLE_IMAGES_COPYRIGHT_WARNING" in MAIN_SOURCE
    assert "WEB_IMAGES_COPYRIGHT_WARNING" in MAIN_SOURCE
    # "Quota ≥ 80%" saiu com o redesign do pool; a contabilidade de quota
    # (queries_used_today) passou a viver no backend de media_generation.
    media_source = (ROOT / "hermes_ui" / "media_generation.py").read_text(encoding="utf-8")
    assert "queries_used_today" in media_source


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
