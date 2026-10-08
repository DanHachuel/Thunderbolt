from pathlib import Path

from integrations.platforms import IntegrationResult
from integrations.upload_routing import _composio_upload, upload_with_default_route


def _settings():
    return {
        "composio_enabled": True,
        "composio_auto_upload": True,
        "composio_api_key": "composio-test-key",
        "composio_user_id": "user-1",
        "composio_tool_slug": "VIDEO_UPLOAD",
        "composio_file_field": "file",
        "composio_arguments_json": "{}",
        "postiz_enabled": False,
    }


def test_composio_is_first_route_when_configured(tmp_path: Path):
    calls = []

    def composio(settings, **kwargs):
        calls.append(("composio", kwargs["video_path"]))
        return IntegrationResult(True, "Composio ok", {"provider_id": "123"})

    def official(*args, **kwargs):
        calls.append(("official", ""))
        return IntegrationResult(True, "Official ok", {})

    result = upload_with_default_route(
        _settings(),
        storage_root=tmp_path,
        channel={"id": "channel-1"},
        account=None,
        video_path=str(tmp_path / "video.mp4"),
        title="Demo",
        composio_publisher=composio,
        official_uploader=official,
    )
    assert result.ok
    assert result.data["route"] == "Composio"
    assert calls == [("composio", str(tmp_path / "video.mp4"))]


def test_composio_failure_falls_back_to_official(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("integrations.upload_routing.official_upload_count", lambda *args, **kwargs: 0)
    calls = []

    def composio(settings, **kwargs):
        calls.append("composio")
        return IntegrationResult(False, "Composio unavailable", {})

    def official(*args, **kwargs):
        calls.append("official")
        return IntegrationResult(True, "Official ok", {})

    result = upload_with_default_route(
        _settings(),
        storage_root=tmp_path,
        channel={"id": "channel-1"},
        account=None,
        video_path=str(tmp_path / "video.mp4"),
        title="Demo",
        composio_publisher=composio,
        official_uploader=official,
    )
    assert result.ok
    assert result.data["route"] == "API Oficial"
    assert calls == ["composio", "official"]


def test_automation_worker_requires_configured_composio_or_another_route():
    source = Path(__file__).parents[1].joinpath("hermes_ui", "pipeline_worker.py").read_text(encoding="utf-8")
    assert "configured_composio" in source
    assert "configured_composio or configured_account_id" in source


def test_current_youtube_composio_tool_uses_connected_account(monkeypatch, tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_execute(*args):
        captured["args"] = args
        return {"successful": True, "data": {"id": "yt-1"}}

    monkeypatch.setattr("integrations.upload_routing.execute_upload", fake_execute)
    result = _composio_upload(
        {**_settings(), "composio_tool_slug": "YOUTUBE_UPLOAD_VIDEO", "composio_file_field": "file", "composio_channel_field": "channel_id"},
        channel={"youtube_channel_id": "UC-other"},
        video_path=str(video),
        privacy_status="unlisted",
        category_id="22",
        language="pt-BR",
    )
    assert result.ok
    assert captured["args"][2] == "YOUTUBE_UPLOAD_VIDEO"
    assert captured["args"][4] == "videoFilePath"
    assert "channel_id" not in captured["args"][5]


def test_youtube_upload_slug_does_not_require_legacy_channel_id(monkeypatch, tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_execute(*args):
        captured["args"] = args
        return {"successful": True, "data": {"id": "yt-2"}}

    monkeypatch.setattr("integrations.upload_routing.execute_upload", fake_execute)
    result = _composio_upload(
        {**_settings(), "composio_tool_slug": "youtube_upload", "composio_file_field": "file"},
        channel={"youtube_id": "UC-legacy"},
        video_path=str(video),
        privacy_status="unlisted",
        category_id="22",
        language="pt-BR",
    )
    assert result.ok
    assert captured["args"][4] == "videoFilePath"


# ── 0.9.68: upload_video resolve à multipart automaticamente ─────────────────


def test_upload_video_alias_resolves_multipart_with_video_file_field(monkeypatch, tmp_path: Path):
    """0.9.68: a resumável cria o vídeo mas entrega bytes que o YouTube
    abandona no processamento; o alias upload_video resolve pela descoberta
    à multipart (YOUTUBE_MULTIPART_UPLOAD_VIDEO) com o campo `videoFile`."""
    import integrations.upload_routing as routing

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_execute(*args):
        captured["args"] = args
        return {"successful": True, "data": {"id": "yt-multipart"}}

    def fake_discover(api_key, user_id, query, toolkit=""):
        return [{"slug": "YOUTUBE_MULTIPART_UPLOAD_VIDEO"}, {"slug": "YOUTUBE_UPLOAD_VIDEO"}]

    monkeypatch.setattr(routing, "execute_upload", fake_execute)
    monkeypatch.setattr("integrations.composio_upload.discover_tools", fake_discover)
    result = _composio_upload(
        {**_settings()},
        channel={"platform": "youtube"},
        video_path=str(video),
        privacy_status="unlisted",
        category_id="22",
        language="pt-BR",
    )
    assert result.ok
    assert captured["args"][2] == "YOUTUBE_MULTIPART_UPLOAD_VIDEO"
    assert captured["args"][4] == "videoFile"


def test_upload_video_alias_falls_back_to_resumable_on_discovery_failure(monkeypatch, tmp_path: Path):
    """Sem descoberta (rede/Composio indisponível), cai-se para a resumável
    validada — o upload continua a funcionar."""
    import integrations.upload_routing as routing
    from integrations.composio_upload import ComposioUploadError

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_execute(*args):
        captured["args"] = args
        return {"successful": True, "data": {"id": "yt-1"}}

    def fake_resolve(*args, **kwargs):
        raise ComposioUploadError("Não foi encontrada uma ferramenta Composio.")

    monkeypatch.setattr(routing, "execute_upload", fake_execute)
    monkeypatch.setattr(routing, "resolve_tool_slug", fake_resolve)
    result = _composio_upload(
        {**_settings()},
        channel={"platform": "youtube"},
        video_path=str(video),
        privacy_status="unlisted",
        category_id="22",
        language="pt-BR",
    )
    assert result.ok
    assert captured["args"][2] == "YOUTUBE_UPLOAD_VIDEO"
    assert captured["args"][4] == "videoFilePath"


def test_explicit_multipart_slug_uses_video_file_field(monkeypatch, tmp_path: Path):
    """Slug explícito multipart mantém o campo correcto `videoFile`."""
    import integrations.upload_routing as routing

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_execute(*args):
        captured["args"] = args
        return {"successful": True, "data": {"id": "yt-2"}}

    monkeypatch.setattr(routing, "execute_upload", fake_execute)
    result = _composio_upload(
        {**_settings()},
        channel={"platform": "youtube", "composio_tool_slug": "YOUTUBE_MULTIPART_UPLOAD_VIDEO"},
        video_path=str(video),
        privacy_status="unlisted",
        category_id="22",
        language="pt-BR",
    )
    assert result.ok
    assert captured["args"][2] == "YOUTUBE_MULTIPART_UPLOAD_VIDEO"
    assert captured["args"][4] == "videoFile"


def test_quota_failure_message_is_actionable(monkeypatch, tmp_path: Path):
    import integrations.upload_routing as routing

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    quota_response = {
        "successful": False,
        "error": "YouTube API did not provide upload URL. Status: 429. Response: {\"error\": {\"code\": 429, \"message\": \"Quota exceeded for quota metric 'Video Uploads' and limit 'Video Uploads per day'\"}}",
        "error_kind": "youtube_upload_quota",
        "error_hint": "A quota diária de uploads do YouTube do projecto Google Cloud usado pela app Composio foi excedida (limite 'Video Uploads per day', cerca de 6 uploads por dia). A quota repõe à meia-noite, hora do Pacífico (~04:00 de Brasília).",
        "http_status": 429,
        "data": {},
        "diagnostics": {},
        "log_id": "",
        "tool_slug": "YOUTUBE_MULTIPART_UPLOAD_VIDEO",
    }

    monkeypatch.setattr(routing, "execute_upload", lambda *args: dict(quota_response))
    result = _composio_upload(
        {**_settings()},
        channel={"platform": "youtube"},
        video_path=str(video),
        privacy_status="unlisted",
        category_id="22",
        language="pt-BR",
    )
    assert not result.ok
    assert "quota diária" in result.message
    assert result.data.get("error_kind") == "youtube_upload_quota"
    assert result.data.get("http_status") == 429
