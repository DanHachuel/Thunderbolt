import json
from pathlib import Path

from integrations import upload_routing


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
STORAGE_SOURCE = (ROOT / "hermes_ui" / "storage.py").read_text(encoding="utf-8")
ROUTING_SOURCE = (ROOT / "integrations" / "upload_routing.py").read_text(encoding="utf-8")


def test_composio_api_ui_uses_internal_operation_lists_and_defaults():
    assert '"upload_video": "Upload Video"' in ROUTING_SOURCE
    assert '"update_video": "Update video"' in ROUTING_SOURCE
    assert '"upload_tiktok_video": "Upload TikTok Video"' in ROUTING_SOURCE
    assert '"upload_instagram_media": "Upload Instagram vídeo/Reel/foto"' in ROUTING_SOURCE
    composio_ui = MAIN_SOURCE.split('with st.expander("Composio", expanded=False):', 1)[1].split('with st.expander("Upload-Post", expanded=False):', 1)[0]
    for label in (
        "Connected account YouTube (ID ou alias)",
        "Slug da ferramenta para Automação Youtube",
        "Toolkit preferido (opcional)",
        "Campo do ficheiro na ferramenta",
        "Campo de privacidade",
        "Campo de categoria",
        "Campo de idioma",
    ):
        assert label not in composio_ui
    assert '"privacyStatus": privacy_value' in ROUTING_SOURCE
    assert '"categoryId": str(category_value)' in ROUTING_SOURCE
    assert '"defaultLanguage": language_locale(' in ROUTING_SOURCE
    assert '"composio_language": "en"' in STORAGE_SOURCE
    assert '"composio_tool_slug": "upload_video"' in STORAGE_SOURCE
    assert '"composio_privacy_status": "unlisted"' in STORAGE_SOURCE
    assert '"composio_category_id": "22"' in STORAGE_SOURCE


def test_composio_backend_forces_video_file_path_and_sanitises_values(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_execute(*args):
        captured["file_field"] = args[4]
        captured["arguments"] = json.loads(args[5])
        return {"successful": True, "data": {}, "log_id": "log-1"}

    monkeypatch.setattr(upload_routing, "execute_upload", fake_execute)
    result = upload_routing._composio_upload(
        {
            "composio_api_key": "composio-test-key",
            "composio_user_id": "user-1",
            "composio_arguments_json": "{}",
        },
        channel={"youtube_channel_id": "UC-PT"},
        video_path=str(video),
        privacy_status="listed",
        category_id="10",
        language="English",
    )
    assert result.ok
    assert captured["file_field"] == "videoFilePath"
    assert captured["arguments"]["privacyStatus"] == "unlisted"
    assert captured["arguments"]["categoryId"] == "22"
    assert captured["arguments"]["defaultLanguage"] == "en-US"


def test_composio_upload_video_does_not_require_a_manual_channel_field(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(upload_routing, "execute_upload", lambda *args: {"successful": True, "data": {}})
    result = upload_routing._composio_upload(
        {
            "composio_api_key": "composio-test-key",
            "composio_user_id": "user-1",
            "composio_arguments_json": "{}",
        },
        channel={},
        video_path=str(video),
    )
    assert result.ok
