import json

from integrations import upload_routing
from integrations.platforms import IntegrationResult


def test_composio_matches_official_upload_parameters(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(*args):
        captured["arguments"] = json.loads(args[-1])
        return {"successful": True, "data": {}, "error": "", "log_id": "log-1"}

    monkeypatch.setattr(upload_routing, "execute_upload", fake_execute)
    result = upload_routing._composio_upload(
        {
            "composio_api_key": "composio-test-key",
            "composio_user_id": "user-1",
            "composio_tool_slug": "YOUTUBE_UPLOAD_VIDEO",
            "composio_file_field": "video",
            "composio_channel_field": "channelId",
            "composio_privacy_field": "privacyStatus",
            "composio_category_field": "categoryId",
            "composio_language_field": "defaultLanguage",
            "composio_arguments_json": "{}",
        },
        channel={"youtube_channel_id": "UC-PT"},
        video_path=str(tmp_path / "video.mp4"),
        category_id="22",
        language="English",
        privacy_status="unlisted",
        title="Vídeo de teste horizontal",
        description="A simple video for only test Upload configuration",
        tags=["#brandnew", "#video", "#test"],
    )
    assert result.ok
    assert captured["arguments"] == {
        "privacyStatus": "unlisted",
        "categoryId": "22",
        "defaultLanguage": "en-US",
        "title": "Vídeo de teste horizontal",
        "description": "A simple video for only test Upload configuration",
        "tags": ["#brandnew", "#video", "#test"],
    }


def test_composio_rejects_conflicting_official_parameters(tmp_path):
    result = upload_routing._composio_upload(
        {
            "composio_api_key": "composio-test-key",
            "composio_user_id": "user-1",
            "composio_tool_slug": "VIDEO_UPLOAD",
            "composio_arguments_json": '{"category_id":"10"}',
        },
        channel={"youtube_channel_id": "UC-PT"},
        video_path=str(tmp_path / "video.mp4"),
        category_id="22",
        language="pt-BR",
        privacy_status="unlisted",
    )
    assert not result.ok
    assert "diferente do upload oficial" in result.message
