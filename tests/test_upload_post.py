import json

from integrations.upload_post import UploadPostAdapter, normalize_upload_post_platforms


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def _settings():
    return {
        "upload_post_enabled": True,
        "upload_post_api_key": "upload-post-test-key",
        "upload_post_username": "thunderbolt-profile",
        "upload_post_platforms": "tiktok, instagram, facebook pages, tiktok",
    }


def test_upload_post_platforms_are_normalized_and_deduplicated():
    assert normalize_upload_post_platforms("TikTok, Instagram, Facebook Pages, TikTok, unsupported") == [
        "tiktok",
        "instagram",
        "facebook",
    ]


def test_upload_post_status_requires_settings():
    result = UploadPostAdapter({}).status()
    assert not result.ok
    assert "desactivado" in result.message
    result = UploadPostAdapter({"upload_post_enabled": True}).status()
    assert not result.ok
    assert "API key" in result.message


def test_upload_post_uploads_multipart_video_with_apikey_auth(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-mp4")
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, "kwargs": kwargs})
        return _Response({"request_id": "request-123", "status": "processing"})

    monkeypatch.setattr("integrations.upload_post.requests.post", fake_post)
    result = UploadPostAdapter(_settings()).upload_video(
        video,
        title="Título",
        description="Descrição",
        platforms=["tiktok", "instagram"],
        async_upload=True,
    )
    assert result.ok
    assert result.data["request_id"] == "request-123"
    assert captured["url"] == "https://api.upload-post.com/api/upload"
    assert captured["kwargs"]["headers"]["Authorization"] == "Apikey upload-post-test-key"
    form_data = captured["kwargs"]["data"]
    assert ("user", "thunderbolt-profile") in form_data
    assert [(key, value) for key, value in form_data if key == "platform[]"] == [("platform[]", "tiktok"), ("platform[]", "instagram")]
    assert ("async_upload", "true") in form_data
    assert captured["kwargs"]["files"]["video"][0] == "video.mp4"


def test_upload_post_rejects_missing_video(tmp_path):
    result = UploadPostAdapter(_settings()).upload_video(tmp_path / "missing.mp4", title="Título")
    assert not result.ok
    assert "não encontrado" in result.message


def test_upload_post_platforms_are_typed_in_api_settings_and_normalised_from_text():
    from pathlib import Path
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    # As plataformas são digitadas como texto nas configurações (com defeito
    # "youtube,tiktok") e normalizadas para valores canónicos no selector do
    # upload via normalize_upload_post_platforms.
    assert 'st.text_input("Plataformas Upload-Post", value=str(settings.get("upload_post_platforms") or "youtube,tiktok")' in source
    assert 'normalize_upload_post_platforms(uploader.platforms)' in source
    assert 'key="upload_post_platforms_selector"' in source
