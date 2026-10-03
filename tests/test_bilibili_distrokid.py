from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

from integrations import bilibili_upload, distrokid_upload
from integrations.bilibili_upload import BILIBILI_API_VERSION, BilibiliApiAdapter, normalise_bilibili_api_cards
from integrations.distrokid_upload import DistroKidAdapter, _cookie_header_to_context_cookies


def test_bilibili_cards_migrate_legacy_credentials_and_keep_values_out_of_public_status():
    cards, changed = normalise_bilibili_api_cards({"bilibili_sessdata": "session-secret", "bilibili_bili_jct": "csrf-secret", "bilibili_buvid3": "buvid-secret"})
    assert changed is True
    assert cards[0]["label"] == "Conta Bilibili 1"
    assert cards[0]["sessdata"] == "session-secret"
    result = BilibiliApiAdapter(cards[0]).status()
    # O bilibili-api-python é dependência declarada desde o commit dde0d8b
    # ("add bilibili and distrokid uploads") e está instalado (17.4.2), logo
    # status() agora detecta o SDK e devolve ok=True; o intent mantém-se: o
    # status público expõe apenas a conta e a versão do SDK, nunca as
    # credenciais migradas (SESSDATA/bili_jct/buvid3).
    assert result.ok is True
    assert result.data["account"] == "Conta Bilibili 1"
    assert result.data["sdk"] == BILIBILI_API_VERSION
    assert "session-secret" not in result.message
    assert "session-secret" not in repr(result.data)
    assert "csrf-secret" not in repr(result.data)
    assert "buvid-secret" not in repr(result.data)


def test_bilibili_connection_uses_credential_check_without_exposing_cookies():
    class Credential:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        async def check_valid(self):
            return True

    with patch.object(bilibili_upload, "_import_sdk", return_value=(Credential, object)):
        result = BilibiliApiAdapter({"label": "Conta 1", "sessdata": "sess", "bili_jct": "csrf", "buvid3": "buvid"}).test_connection()
    assert result.ok is True
    assert result.data["valid"] is True
    assert "sess" not in repr(result.data)


def test_bilibili_upload_builds_video_uploader_contract_and_returns_bvid(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"cover")
    captured = {}

    class Credential:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Page:
        def __init__(self, *args):
            captured["page"] = args

    class Uploader:
        def __init__(self, pages, meta, credential, cover=""):
            captured.update(pages=pages, meta=meta, credential=credential, cover=cover)
        async def start(self):
            return {"bvid": "BV123", "aid": 123}

    sdk = types.SimpleNamespace(VideoUploaderPage=Page, VideoUploader=Uploader)
    with patch.object(bilibili_upload, "_import_sdk", return_value=(Credential, sdk)):
        result = BilibiliApiAdapter({"label": "Conta 1", "sessdata": "sess", "bili_jct": "csrf", "buvid3": "buvid"}).upload_video(video, title="Título", description="Descrição", tags="tag1,tag2", tid=130, cover_path=cover)
    assert result.ok is True
    assert result.data["bvid"] == "BV123"
    assert captured["meta"]["tid"] == 130
    assert captured["meta"]["tag"] == "tag1,tag2"
    assert captured["page"][0] == str(video)
    assert "sess" not in repr(result.data)


def test_bilibili_upload_rejects_invalid_tag_count_before_sdk(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    with patch.object(bilibili_upload, "_import_sdk") as import_sdk:
        result = BilibiliApiAdapter({"sessdata": "sess", "bili_jct": "csrf", "buvid3": "buvid"}).upload_video(video, title="Título", tags="")
    assert result.ok is False
    assert "tags" in result.message


def test_distrokid_cookie_header_is_converted_without_logging_values():
    cookies = _cookie_header_to_context_cookies("sid=secret; other=value")
    assert {item["name"] for item in cookies} == {"sid", "other"}
    assert all(item["domain"] == ".distrokid.com" for item in cookies)
    result = DistroKidAdapter({"distrokid_enabled": True, "distrokid_cookie": "sid=secret"}).status()
    assert result.ok is True
    assert "secret" not in repr(result.data)


def test_distrokid_prepare_upload_keeps_final_submit_manual(monkeypatch, tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"audio")
    calls = {}

    class FakePage:
        url = "https://distrokid.com/new/"
        def goto(self, *args, **kwargs):
            calls["goto"] = args[0]
        def wait_for_selector(self, *args, **kwargs):
            calls["wait_for_selector"] = args[0]
    class FakeContext:
        def add_cookies(self, value):
            calls["cookies"] = value
        def new_page(self):
            return FakePage()
        def close(self):
            calls["context_closed"] = True
    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()
        def close(self):
            calls["browser_closed"] = True
    class FakeChromium:
        def launch(self, **kwargs):
            calls["launch"] = kwargs
            return FakeBrowser()
    class FakePlaywright:
        chromium = FakeChromium()
        def stop(self):
            calls["stopped"] = True
    class Manager:
        def start(self):
            return FakePlaywright()
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: Manager()
    sync_api.TimeoutError = type("TimeoutError", (Exception,), {})
    playwright = types.ModuleType("playwright")
    playwright.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setattr(DistroKidAdapter, "_fill_form", staticmethod(lambda *args: calls.update(fill=True)))
    result = DistroKidAdapter({"distrokid_enabled": True, "distrokid_cookie": "sid=secret", "distrokid_account": "Conta"}).prepare_upload(
        [{"path": str(audio), "title": "Faixa"}], artist="Artista", release_title="Release"
    )
    assert result.ok is True
    assert result.data["manual_submit"] is True
    assert result.data["tracks"] == 1
    assert calls["fill"] is True
    assert "secret" not in repr(result.data)
