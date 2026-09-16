from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_test_upload_videos_tab_is_between_ai_and_voice_test():
    tabs = 'api_keys_tab, upload_api_keys_tab, subtitles_tab, ffmpeg_tab, ai_influencers_tab, test_upload_videos_tab, voice_test_tab = render_localized_tabs(["API Keys", "API Keys Upload", "Legendas", "FFmpeg", "AI Influencers", "Test Upload Videos", "Teste de Voz"])'
    assert tabs in SOURCE
    assert SOURCE.index("with ai_influencers_tab:") < SOURCE.index("with test_upload_videos_tab:") < SOURCE.index("with voice_test_tab:")


def test_test_upload_videos_has_requested_modes_and_operations():
    for label in ("Composio", "API Youtube", "YouTube Frontend API", "Postiz", "Upload-Post"):
        assert label in SOURCE
    for label in ("Canais YouTube", "Canais Tiktok", "Contas Instagram", "Contas Bilibili", "Facebook Pages"):
        assert label in SOURCE
    assert 'st.button("Testar Upload"' in SOURCE


def test_seed_test_videos_are_packaged_and_described():
    for filename in ("test-horizontal.mp4", "test-vertical.mp4"):
        path = ROOT / "seed" / "test_upload_videos" / filename
        assert path.is_file()
        assert path.stat().st_size > 0
    assert "Vídeo horizontal para YouTube e Bilibili" in SOURCE
    assert "Vídeo vertical para YouTube Shorts, TikTok, Instagram e Facebook Pages" in SOURCE
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    assert '"seed/test_upload_videos/*.mp4"' in package
