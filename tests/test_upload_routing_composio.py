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


# ── 0.9.65: upload_video volta à ferramenta validada; quota accionável ──────


def test_upload_video_alias_uses_the_validated_upload_video_tool(monkeypatch, tmp_path: Path):
    # 0.9.65: restaurado o comportamento pré-0.9.56. O multipart exige o
    # campo `videoFile`, mas o Thunderbolt injecta o ficheiro em
    # `videoFilePath` (o campo de YOUTUBE_UPLOAD_VIDEO) — o upload falhava
    # com 400 "Following fields are missing: {'videoFile'}".
    import integrations.upload_routing as routing

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_execute(*args):
        captured["args"] = args
        return {"successful": True, "data": {"id": "yt-1"}}

    def fail_resolve(*args, **kwargs):
        raise AssertionError("o alias upload_video não corre a descoberta de ferramentas")

    monkeypatch.setattr(routing, "execute_upload", fake_execute)
    monkeypatch.setattr(routing, "resolve_tool_slug", fail_resolve)
    result = _composio_upload(
        {**_settings(), "composio_tool_slug": "upload_video"},
        channel={"platform": "youtube"},
        video_path=str(video),
        privacy_status="unlisted",
        category_id="22",
        language="pt-BR",
    )
    assert result.ok
    assert captured["args"][2] == "YOUTUBE_UPLOAD_VIDEO"
    assert captured["args"][4] == "videoFilePath"


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
        "tool_slug": "YOUTUBE_UPLOAD_VIDEO",
    }

    monkeypatch.setattr(routing, "execute_upload", lambda *args: dict(quota_response))
    result = _composio_upload(
        {**_settings(), "composio_tool_slug": "upload_video"},
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


def test_test_upload_panel_survives_the_log_rerun():
    """0.9.66: o painel "Resultado do teste de upload" não pode ficar vazio.

    O st.rerun() que activa o botão Download Log recriava o st.empty() vazio
    e o resultado do teste desaparecia — o utilizador ficava sem saber o que
    deu no upload. O resultado (e os diagnósticos) persistem agora no
    session_state e são renderizados fora do bloco do botão.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'result_state_key = "test_upload_last_result"' in source
    assert 'diagnostics_state_key = "test_upload_last_diagnostics"' in source
    # render persistente fora do bloco execute_upload
    assert "last_result = st.session_state.get(result_state_key)" in source
    assert "status_panel.success(last_result[\"message\"])" in source
    assert "status_panel.error(last_result[\"message\"])" in source
    assert "status_panel.warning(last_result[\"message\"])" in source
    # o caminho de resultado persiste antes do rerun
    assert 'st.session_state[result_state_key] = {"ok": bool(result.ok), "message": result.message}' in source
    # o caminho de excepção persiste a mensagem de falha
    assert 'st.session_state[result_state_key] = {"ok": False, "message": failure_message}' in source
    # os diagnósticos também sobrevivem
    assert "last_diagnostics = st.session_state.get(diagnostics_state_key)" in source


# ── 0.9.67: multipart opcional com o campo correcto (videoFile) ──────────────


def test_multipart_tool_uses_video_file_field(monkeypatch, tmp_path: Path):
    """A ferramenta YOUTUBE_MULTIPART_UPLOAD_VIDEO recebe o ficheiro em
    `videoFile` (não `videoFilePath`) — sem isto devolvia 400."""
    import integrations.upload_routing as routing

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_execute(*args):
        captured["args"] = args
        return {"successful": True, "data": {"id": "yt-multipart"}}

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


def test_multipart_alias_resolves_via_discovery(monkeypatch, tmp_path: Path):
    """O alias `multipart_upload_video` resolve pela descoberta à ferramenta
    multipart do Composio (para quem a quiser usar no canal)."""
    import integrations.upload_routing as routing

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    captured = {}

    def fake_execute(*args):
        captured["args"] = args
        return {"successful": True, "data": {"id": "yt-2"}}

    def fake_discover(api_key, user_id, query, toolkit=""):
        assert query == "Multipart Upload Video"
        return [{"slug": "YOUTUBE_MULTIPART_UPLOAD_VIDEO"}, {"slug": "YOUTUBE_UPLOAD_VIDEO"}]

    monkeypatch.setattr(routing, "execute_upload", fake_execute)
    monkeypatch.setattr("integrations.composio_upload.discover_tools", fake_discover)
    result = _composio_upload(
        {**_settings()},
        channel={"platform": "youtube", "composio_tool_slug": "multipart_upload_video"},
        video_path=str(video),
        privacy_status="unlisted",
        category_id="22",
        language="pt-BR",
    )
    assert result.ok
    assert captured["args"][2] == "YOUTUBE_MULTIPART_UPLOAD_VIDEO"
    assert captured["args"][4] == "videoFile"
