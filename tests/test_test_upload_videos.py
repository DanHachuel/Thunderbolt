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


def test_local_video_player_uses_native_streamlit_video_without_base64():
    block = SOURCE.split("def _render_local_video_player", 1)[1].split("def ", 1)[0]
    assert "if not path.is_file()" in block
    assert 'st.warning(f"Vídeo não encontrado: {path.name}")' in block
    assert 'video_kwargs: dict[str, Any] = {"format": mimetypes.guess_type(path.name)[0] or "video/mp4"}' in block
    assert 'video_signature = inspect.signature(st.video)' in block
    assert 'video_kwargs["width"] = width' in block
    assert 'st.video(str(path), **video_kwargs)' in block
    assert "_file_bytes(path)" not in block
    assert "base64" not in block
    assert "st.html(" not in block


def test_test_videos_seed_upload_metadata_is_specific_and_complete():
    assert '"title": "Vídeo de teste horizontal"' in SOURCE
    assert '"description": "A simple video for only test Upload configuration"' in SOURCE
    assert '"title": "Vídeo de teste vertical"' in SOURCE
    assert '"description": "A short video for only test Upload configuration"' in SOURCE
    assert SOURCE.count('["#brandnew", "#video", "#test"]') == 2
    assert 'upload_metadata = _test_video_upload_metadata(selected_video)' in SOURCE
    assert 'tags = upload_metadata["tags"]' in SOURCE
    assert 'tags deve ser uma lista de strings não vazias' in SOURCE


def test_test_upload_videos_displays_composio_diagnostics():
    assert 'diagnostics = result.data.get("diagnostics")' in SOURCE
    assert 'st.expander("Logs de diagnóstico Composio", expanded=True)' in SOURCE
    assert 'st.json(diagnostics)' in SOURCE


def test_test_upload_videos_has_adjacent_download_log_button():
    block = SOURCE.split("def _render_test_upload_videos", 1)[1].split("def ", 1)[0]
    assert 'st.button("Testar Upload"' in block
    assert 'st.download_button(' in block
    assert '"Download Log"' in block
    assert 'file_name=saved_log.get("filename", "Log_Upload_Composio.md")' in block
    assert 'filename = f"Log_Upload_Composio-{timestamp}.md"' in SOURCE
    assert 'st.session_state[log_state_key]' in block
