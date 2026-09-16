from pathlib import Path

import pytest

from hermes_ui import media_downloader, storage


def _isolated_storage(tmp_path):
    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.TIKTOK_PROMPT_MASTERS = storage.STORAGE / "tiktok" / "prompts_master"
    storage.MEDIA_DOWNLOADS = storage.STORAGE / "downloads"
    storage.ensure_storage()
    return storage


def test_normalize_urls_rejects_non_http_and_cli_flags():
    assert media_downloader.normalize_urls(" https://example.com/video\nhttps://example.com/video ") == ["https://example.com/video"]
    with pytest.raises(ValueError, match="URL inválida"):
        media_downloader.normalize_urls("ftp://example.com/video")
    with pytest.raises(ValueError, match="opções"):
        media_downloader.normalize_urls("--cookies cookies.txt")


def test_build_options_are_constrained_for_video_and_audio(tmp_path, monkeypatch):
    _isolated_storage(tmp_path)
    fake_deno = tmp_path / "deno"
    fake_deno.write_bytes(b"deno")
    monkeypatch.setattr(media_downloader, "_deno_runtime_path", lambda: str(fake_deno))
    video = media_downloader.build_download_options(mode="video", quality="720p ou inferior", container="mp4", allow_playlist=False, download_subtitles=True, embed_metadata=True)
    assert video["noplaylist"] is True
    assert "height<=720" in video["format"]
    assert video["merge_output_format"] == "mp4"
    assert video["writesubtitles"] is True
    assert video["addmetadata"] is True
    assert "%(title).200B" in video["outtmpl"]
    assert video["js_runtimes"] == {"deno": {"path": str(fake_deno)}}
    audio = media_downloader.build_download_options(mode="audio", audio_format="mp3", allow_playlist=True)
    assert audio["noplaylist"] is False
    assert audio["format"] == "bestaudio/best"
    assert audio["postprocessors"][0]["preferredcodec"] == "mp3"


def test_build_options_support_image_thumbnail_containers(tmp_path, monkeypatch):
    _isolated_storage(tmp_path)
    fake_deno = tmp_path / "deno"
    fake_deno.write_bytes(b"deno")
    monkeypatch.setattr(media_downloader, "_deno_runtime_path", lambda: str(fake_deno))

    image = media_downloader.build_download_options(mode="image", quality="Alta", container="webp")

    assert image["writethumbnail"] is True
    assert image["skip_download"] is True
    assert image["postprocessors"] == [{"key": "FFmpegThumbnailsConvertor", "format": "webp"}]
    assert image["js_runtimes"] == {"deno": {"path": str(fake_deno)}}

    with pytest.raises(ValueError, match="Contentor de imagem"):
        media_downloader.build_download_options(mode="image", container="mp4")


def test_successful_download_persists_file_and_notification(tmp_path, monkeypatch):
    _isolated_storage(tmp_path)
    events = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def extract_info(self, url, download=True):
            output = Path(self.options["paths"]["home"]) / "demo.mp4"
            output.write_bytes(b"video")
            for hook in self.options.get("progress_hooks", []):
                hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10, "filename": str(output)})
                hook({"status": "finished", "filename": str(output)})
            return {"title": "Vídeo demo", "filepath": str(output)}

        def close(self):
            return None

    monkeypatch.setattr(media_downloader, "yt_dlp", type("FakeModule", (), {"YoutubeDL": FakeYoutubeDL}))
    result = media_downloader.download_media("https://example.com/video", progress_callback=events.append)
    assert result[0]["status"] == "completed"
    assert result[0]["title"] == "Vídeo demo"
    assert result[0]["files"] == ["demo.mp4"]
    assert Path(storage.MEDIA_DOWNLOADS / "demo.mp4").is_file()
    assert media_downloader.list_media_downloads()[0]["operation_id"] == result[0]["operation_id"]
    assert any(item.get("hook_status") == "finished" for item in events)
    notifications = storage.read_json("notifications.json", [])
    assert notifications[0]["event_type"] == "media_download_completed"


def test_failed_download_is_persisted_and_notifies_without_secrets(tmp_path, monkeypatch):
    _isolated_storage(tmp_path)

    class FailingYoutubeDL:
        def __init__(self, options):
            self.options = options

        def extract_info(self, url, download=True):
            raise RuntimeError("Bearer secret-token falhou")

        def close(self):
            return None

    monkeypatch.setattr(media_downloader, "yt_dlp", type("FakeModule", (), {"YoutubeDL": FailingYoutubeDL}))
    result = media_downloader.download_media("https://example.com/private")
    assert result[0]["status"] == "failed"
    assert "secret-token" not in result[0]["error"]
    notifications = storage.read_json("notifications.json", [])
    assert notifications[0]["event_type"] == "media_download_failed"
    assert "secret-token" not in str(notifications)


def test_media_history_clear_does_not_remove_download_files(tmp_path):
    _isolated_storage(tmp_path)
    output = storage.MEDIA_DOWNLOADS / "keep.mp4"
    output.write_bytes(b"keep")
    media_downloader._upsert_history({"operation_id": "op-1", "status": "completed", "files": ["keep.mp4"], "title": "Keep"})
    assert media_downloader.clear_media_download_history() == 1
    assert output.is_file()
    assert media_downloader.list_media_downloads() == []
