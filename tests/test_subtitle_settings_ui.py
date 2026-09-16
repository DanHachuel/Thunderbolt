from pathlib import Path


SOURCE = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")


def test_subtitle_tab_is_between_upload_and_ai_influencers():
    tabs = 'api_keys_tab, upload_api_keys_tab, subtitles_tab, ffmpeg_tab, ai_influencers_tab, test_upload_videos_tab, voice_test_tab = render_localized_tabs(["API Keys", "API Keys Upload", "Legendas", "FFmpeg", "AI Influencers", "Test Upload Videos", "Teste de Voz"])'
    assert tabs in SOURCE
    assert SOURCE.index("with upload_api_keys_tab:") < SOURCE.index("with subtitles_tab:") < SOURCE.index("with ai_influencers_tab:")


def test_subtitle_tab_exposes_edge_and_whisper_modes_without_changing_defaults():
    block = SOURCE[SOURCE.index("with subtitles_tab:"):SOURCE.index("with ai_influencers_tab:")]
    assert 'st.subheader("Legendas")' in block
    assert 'subtitle_provider' in block
    assert '"edge"' in block and '"whisper"' in block
    assert "whisper_model_size" in block
    assert "whisper_device" in block
    assert "whisper_compute_type" in block
    assert "sync_moneyprinter_config(settings, subtitle_moneyprinter_path)" in block
    assert 'settings.setdefault("subtitle_provider"' not in block


def test_subtitle_tab_describes_both_generation_modes():
    block = SOURCE[SOURCE.index("with subtitles_tab:"):SOURCE.index("with ai_influencers_tab:")]
    for text in ("Modo", "Velocidade", "Requisitos de Hardware", "Qualidade", "Rápida", "Lenta", "GPU recomendada"):
        assert text in block
