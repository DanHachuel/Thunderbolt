import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations import composio_upload


def test_parse_arguments_requires_object():
    assert composio_upload.parse_arguments('{"title": "Demo"}') == {"title": "Demo"}
    with pytest.raises(composio_upload.ComposioUploadError):
        composio_upload.parse_arguments("[]")
    with pytest.raises(composio_upload.ComposioUploadError):
        composio_upload.parse_arguments("not-json")


def test_execute_upload_injects_selected_file_field(monkeypatch, tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    captured = {}

    class FakeTools:
        def execute(self, slug, **kwargs):
            captured.update(slug=slug, kwargs=kwargs)
            return SimpleNamespace(data={"remote_id": "123"}, error=None, log_id="log-123")

    class FakeAccounts:
        def list(self, **kwargs):
            return {"items": [{"id": "youtube-test", "alias": "Demo", "toolkit": "youtube"}]}

    class FakeClient:
        tools = FakeTools()
        connected_accounts = FakeAccounts()

    monkeypatch.setattr(composio_upload, "_client", lambda *args, **kwargs: FakeClient())
    result = composio_upload.execute_upload("ak_123456789", "user-1", "DRIVE_UPLOAD_FILE", str(video), "file", '{"title":"Demo"}')
    assert result["successful"] is True
    assert result["log_id"] == "log-123"
    assert captured["slug"] == "DRIVE_UPLOAD_FILE"
    assert captured["kwargs"]["arguments"]["file"] == str(video.resolve())
    assert captured["kwargs"]["arguments"]["title"] == "Demo"
    assert "ak_123456789" not in json.dumps(result)


def test_execute_upload_rejects_existing_file_value(tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    with pytest.raises(composio_upload.ComposioUploadError, match="já contém"):
        composio_upload.execute_upload("ak_123456789", "user-1", "TOOL", str(video), "file", '{"file":"other.mp4"}')


def test_response_reads_nested_error_and_success_flags():
    result = composio_upload._response(SimpleNamespace(success=False, data={"message": "uploadLimitExceeded"}, request_id="req-1"))
    assert result["successful"] is False
    assert result["error"] == "uploadLimitExceeded"
    assert result["log_id"] == "req-1"


def test_resolve_upload_video_alias_uses_a_real_youtube_slug(monkeypatch):
    monkeypatch.setattr(
        composio_upload,
        "discover_tools",
        lambda *args, **kwargs: [
            {"slug": "YOUTUBE_UPLOAD_VIDEO", "name": "Upload Video", "toolkit": "youtube"},
            {"slug": "YOUTUBE_UPDATE_VIDEO", "name": "Update Video", "toolkit": "youtube"},
        ],
    )

    assert composio_upload.resolve_tool_slug("ak_123456789", "user-1", "upload_video") == "YOUTUBE_UPLOAD_VIDEO"


def test_resolve_upload_video_alias_reports_missing_real_tool(monkeypatch):
    monkeypatch.setattr(composio_upload, "discover_tools", lambda *args, **kwargs: [])

    with pytest.raises(composio_upload.ComposioUploadError, match="Não foi encontrada"):
        composio_upload.resolve_tool_slug("ak_123456789", "user-1", "upload_video")


def test_connected_account_alias_resolves_to_technical_id(monkeypatch):
    class FakeAccounts:
        def list(self, **kwargs):
            assert kwargs["user_ids"] == ["user-1"]
            assert kwargs["statuses"] == ["ACTIVE"]
            return {"items": [{"id": "youtube_fifo-wrote", "alias": "Grace-Gospel", "toolkit": "youtube"}]}

    client = SimpleNamespace(connected_accounts=FakeAccounts())
    assert composio_upload._connected_account_id(client, "user-1", "youtube", "Grace-Gospel") == "youtube_fifo-wrote"


def test_connected_account_missing_alias_does_not_fall_through_to_invalid_selector():
    class FakeAccounts:
        def list(self, **kwargs):
            return {"items": [{"id": "youtube_fifo-wrote", "alias": "Grace-Gospel", "toolkit": "youtube"}]}

    client = SimpleNamespace(connected_accounts=FakeAccounts())
    with pytest.raises(composio_upload.ComposioUploadError, match="não foi encontrada"):
        composio_upload._connected_account_id(client, "user-1", "youtube", "Conta-Inexistente")


def test_connected_account_v31_toolkit_slug_is_supported():
    class FakeAccounts:
        def list(self, **kwargs):
            assert kwargs["toolkit_slugs"] == ["youtube"]
            return {"items": [{"id": "youtube_fifo-wrote", "alias": "Grace-Gospel", "toolkit_slug": "youtube"}]}

    client = SimpleNamespace(connected_accounts=FakeAccounts())
    assert composio_upload._connected_account_id(client, "user-1", "youtube", "Grace-Gospel") == "youtube_fifo-wrote"


def test_connected_account_sdk_model_with_camel_case_id_and_omitted_toolkit_resolves_brick_by_brick_wealth():
    class FakeAccounts:
        def list(self, **kwargs):
            return {"items": [{
                "connectionId": "youtube_brick-by-brick-wealth",
                "alias": "Brick-by-Brick-Wealth",
                "status": "ACTIVE",
            }]}

    client = SimpleNamespace(connected_accounts=FakeAccounts())
    assert composio_upload._connected_account_id(
        client, "user-1", "youtube", "Brick-by-Brick-Wealth"
    ) == "youtube_brick-by-brick-wealth"


def test_connected_account_alias_resolves_nested_sdk_connection_id():
    class FakeAccounts:
        def list(self, **kwargs):
            return SimpleNamespace(data={"items": [{
                "connection_id": "youtube_rine-pirl",
                "alias": "The-Financial-Mechanics",
                "toolkit": "youtube",
            }]})

    client = SimpleNamespace(connected_accounts=FakeAccounts())
    assert composio_upload._connected_account_id(
        client,
        "user-1",
        "youtube",
        "The-Financial-Mechanics",
    ) == "youtube_rine-pirl"


def test_connected_account_alias_uses_memory_cache():
    calls = 0

    class FakeAccounts:
        def list(self, **kwargs):
            nonlocal calls
            calls += 1
            return {"items": [{
                "id": "youtube_cached",
                "alias": "Cached-Account",
                "toolkit": "youtube",
            }]}

    client = SimpleNamespace(connected_accounts=FakeAccounts())
    assert composio_upload._connected_account_id(client, "cache-user", "youtube", "Cached-Account") == "youtube_cached"
    assert composio_upload._connected_account_id(client, "cache-user", "youtube", "Cached-Account") == "youtube_cached"
    assert calls == 1


def test_duplicate_connected_account_alias_is_rejected():
    class FakeAccounts:
        def list(self, **kwargs):
            return {"items": [
                {"id": "youtube-one", "alias": "Duplicated", "toolkit": "youtube"},
                {"id": "youtube-two", "alias": "Duplicated", "toolkit": "youtube"},
            ]}

    with pytest.raises(composio_upload.ComposioUploadError, match="múltiplas"):
        composio_upload._connected_account_id(SimpleNamespace(connected_accounts=FakeAccounts()), "duplicate-user", "youtube", "Duplicated")


def test_youtube_upload_scope_is_required():
    client = SimpleNamespace(connected_accounts=SimpleNamespace(get=lambda **kwargs: {"data": {"scopes": ["https://www.googleapis.com/auth/youtube.readonly"]}}))
    with pytest.raises(composio_upload.YouTubeUploadScopeMissingError, match="youtube.force-ssl"):
        composio_upload.ensure_youtube_upload_scope(client, "youtube-readonly", "Read-only")


def test_youtube_upload_scope_is_accepted():
    client = SimpleNamespace(connected_accounts=SimpleNamespace(get=lambda **kwargs: {"data": {"scopes": [composio_upload.YOUTUBE_UPLOAD_SCOPE]}}))
    composio_upload.ensure_youtube_upload_scope(client, "youtube-writable", "Writable")


def test_youtube_upload_accepts_current_video_file_path(monkeypatch, tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    captured = {}

    class FakeTools:
        def execute(self, slug, **kwargs):
            captured.update(slug=slug, kwargs=kwargs)
            return {"successful": True, "data": {"id": "video-1"}}

    class FakeAccounts:
        def list(self, **kwargs):
            return {"items": [{"id": "youtube-test", "alias": "Demo", "toolkit": "youtube"}]}

        def get(self, **kwargs):
            return {"data": {"scopes": [composio_upload.YOUTUBE_UPLOAD_SCOPE]}}

    monkeypatch.setattr(composio_upload, "_client", lambda *args, **kwargs: SimpleNamespace(tools=FakeTools(), connected_accounts=FakeAccounts()))
    result = composio_upload.execute_upload("ak_123456789", "user-1", "YOUTUBE_UPLOAD_VIDEO", str(video), "videoFilePath", "{}")
    assert result["successful"] is True
    assert captured["slug"] == "YOUTUBE_UPLOAD_VIDEO"
    assert captured["kwargs"]["arguments"]["videoFilePath"] == str(video.resolve())


def test_discover_tools_normalises_sdk_items(monkeypatch):
    class FakeTools:
        def get(self, user_id, **kwargs):
            assert user_id == "user-1"
            assert kwargs["search"] == "upload video"
            return [SimpleNamespace(slug="DRIVE_UPLOAD_FILE", name="Upload file", description="Upload", toolkit=SimpleNamespace(slug="drive"), input_parameters={"type": "object"})]

    class FakeClient:
        tools = FakeTools()

    monkeypatch.setattr(composio_upload, "_client", lambda *args, **kwargs: FakeClient())
    result = composio_upload.discover_tools("ak_123456789", "user-1", "upload video")
    assert result[0]["slug"] == "DRIVE_UPLOAD_FILE"
    assert result[0]["toolkit"] == "drive"
    assert result[0]["schema"] == {"type": "object"}


def test_source_contains_composio_ui_contract():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert "Upload via Composio" in source
    assert "upload_composio_api_key" in source
    assert "test_configuration" in source
    assert "Secção reservada para uma futura integração Composio" not in source
