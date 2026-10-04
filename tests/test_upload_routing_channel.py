import json
from pathlib import Path

from integrations import upload_routing


def _settings(arguments="{}"):
    return {
        "composio_enabled": True,
        "composio_auto_upload": True,
        "composio_api_key": "composio-test-key",
        "composio_user_id": "user-1",
        "composio_tool_slug": "YOUTUBE_UPLOAD",
        "composio_file_field": "video",
        "composio_channel_field": "channel_id",
        "composio_arguments_json": arguments,
        "postiz_enabled": False,
    }


def test_default_composio_route_injects_task_youtube_channel_id(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_execute(api_key, user_id, slug, video_path, file_field, arguments_json, connected_account_id=""):
        captured.update(api_key=api_key, user_id=user_id, slug=slug, video_path=video_path, file_field=file_field, arguments=json.loads(arguments_json), connected_account_id=connected_account_id)
        return {"successful": True, "data": {"remote_id": "abc"}, "error": "", "log_id": "log-1"}

    monkeypatch.setattr(upload_routing, "execute_upload", fake_execute)
    result = upload_routing.upload_with_default_route(
        _settings('{"title":"Demo"}'),
        storage_root=tmp_path,
        channel={
            "id": "local-1",
            "youtube_channel_id": "UC-CORRECT",
            # A conta conectada é resolvida por canal antes do upload (cache);
            # sem este cache o teste faria chamadas reais de discovery ao Composio.
            "composio": {"connected_account_id": "The-Financial-Mechanics", "user_id": "user-1"},
        },
        account=None,
        video_path=str(tmp_path / "video.mp4"),
        title="Demo",
    )
    assert result.ok
    assert result.data["route"] == "Composio"
    # Desde 1ac6068 ("remover parâmetros técnicos da UI Composio") a ferramenta
    # oficial YOUTUBE_UPLOAD_VIDEO liga o canal via conta conectada e os
    # argumentos carregam os metadados oficiais do YouTube (privacyStatus,
    # categoryId, defaultLanguage) em vez do antigo channel_id snake_case.
    assert captured["arguments"] == {
        "title": "Demo",
        "description": "",
        "tags": [],
        "privacyStatus": "unlisted",
        "categoryId": "22",
        "defaultLanguage": "pt-BR",
    }
    assert captured["file_field"] == "videoFilePath"
    assert captured["connected_account_id"] == "The-Financial-Mechanics"


def test_default_composio_route_blocks_conflicting_channel(monkeypatch, tmp_path: Path):
    called = []

    def fake_execute(*args):
        called.append(args)
        return {"successful": True, "data": {}, "error": "", "log_id": ""}

    monkeypatch.setattr(upload_routing, "execute_upload", fake_execute)
    monkeypatch.setattr(upload_routing, "resolve_tool_slug", lambda api_key, user_id, slug, toolkit="": slug)
    result = upload_routing._composio_upload(
        _settings('{"channel_id":"UC-WRONG"}'),
        channel={
            "id": "local-1",
            "youtube_channel_id": "UC-CORRECT",
            # Ferramenta genérica (não-oficial do YouTube): o campo de canal
            # continua a ser injectado e validado nos argumentos.
            "composio_tool_slug": "GENERIC_TOOL",
            "composio": {"connected_account_id": "ca_test", "user_id": "user-1"},
        },
        video_path=str(tmp_path / "video.mp4"),
    )
    assert not result.ok
    assert "outro canal" in result.message
    assert called == []


def test_automation_source_keeps_channel_field_internal():
    main_source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    routing_source = Path(__file__).parents[1].joinpath("integrations", "upload_routing.py").read_text(encoding="utf-8")
    # Desde 1ac6068 os parâmetros técnicos do Composio não são editáveis na UI:
    # o campo de canal é resolvido internamente (defeito 'channel_id') no backend
    # e é removido das configurações guardadas pelo utilizador.
    assert 'channel_field = str(settings.get("composio_channel_field") or "channel_id").strip()' in routing_source
    assert 'settings.pop("composio_channel_field", None)' in main_source
