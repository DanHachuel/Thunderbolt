from __future__ import annotations

from integrations import upload_routing
from integrations.platforms import IntegrationResult


def test_uncertain_social_auto_upload_stops_other_routes(monkeypatch, tmp_path):
    result = upload_routing.upload_with_default_route(
        {"youtube_automation_auto_upload": True, "social_auto_upload_enabled": True},
        storage_root=tmp_path,
        channel={"id": "channel1", "name": "Canal", "platform": "youtube"},
        account=None,
        video_path="video.mp4",
        title="Título",
        social_auto_upload_publisher=lambda **kwargs: IntegrationResult(False, "Verifique manualmente.", {"reason": "upload_uncertain", "checkpoint_state": "upload_uncertain"}),
        social_auto_upload_session_ready=True,
        task_id="task1",
        official_uploader=lambda *args, **kwargs: IntegrationResult(False, "API indisponível", {}),
        direct_uploader=lambda *args, **kwargs: IntegrationResult(False, "Sem sessão directa", {}),
        postiz_publisher=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deve chamar Postiz")),
    )

    assert result.ok is False
    assert result.data["reason"] == "upload_uncertain"
    assert result.data["route"] == "social-auto-upload"
