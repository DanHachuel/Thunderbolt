from __future__ import annotations

import json
import os
import time

import pytest

from hermes_ui import social_auto_upload_backend as backend
from hermes_ui import storage


def _storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", root / "tiktok" / "prompts_master")
    monkeypatch.setattr(storage, "MEDIA_DOWNLOADS", root / "media_downloads")
    monkeypatch.setattr(storage, "NICHES_DATA", root / "data" / "niches")
    storage.ensure_storage()
    return root


def test_storage_state_requires_nonempty_cookie_for_platform_domain(tmp_path):
    state = tmp_path / "storage_state.json"
    state.write_text(json.dumps({"cookies": [{"name": "SID", "value": "", "domain": ".youtube.com"}]}), encoding="utf-8")
    assert backend.validate_storage_state(state, "youtube.com")[0] is False
    # 1.0.29: cookies ESSENCIAIS de sessão (SID+HSID+SSID) são obrigatórios —
    # cookies de visitante (VISITOR_INFO1_LIVE) já não passam (falso positivo).
    state.write_text(json.dumps({"cookies": [
        {"name": "VISITOR_INFO1_LIVE", "value": "visitor", "domain": ".youtube.com"},
    ]}), encoding="utf-8")
    assert backend.validate_storage_state(state, "youtube.com")[0] is False
    assert "O login falhou ou foi cancelado. Tente novamente." in backend.validate_storage_state(state, "youtube.com")[1]
    state.write_text(json.dumps({"cookies": [
        {"name": "SID", "value": "s", "domain": ".youtube.com"},
        {"name": "HSID", "value": "h", "domain": ".youtube.com"},
        {"name": "SSID", "value": "ss", "domain": ".youtube.com"},
    ]}), encoding="utf-8")
    assert backend.validate_storage_state(state, "youtube.com")[0] is True
    assert backend.validate_storage_state(state, "tiktok.com")[0] is False
    # os essenciais em .google.com também validam o login Google/YouTube
    state.write_text(json.dumps({"cookies": [
        {"name": "SID", "value": "s", "domain": ".google.com"},
        {"name": "HSID", "value": "h", "domain": ".google.com"},
        {"name": "SSID", "value": "ss", "domain": ".google.com"},
    ]}), encoding="utf-8")
    assert backend.validate_storage_state(state, "youtube.com")[0] is True
    # plataformas sem mapa de essenciais mantêm a regra antiga (não vazio)
    state.write_text(json.dumps({"cookies": [{"name": "SESSDATA", "value": "bili", "domain": ".bilibili.com"}]}), encoding="utf-8")
    assert backend.validate_storage_state(state, "bilibili.com")[0] is True
    assert backend.session_cookies_for_domain({"cookies": [{"name": "SID", "value": "session", "domain": "studio.youtube.com"}]})
    assert not backend.session_cookies_for_domain({"cookies": [{"name": "SID", "value": "session", "domain": "evilnotyoutube.com"}]})


def test_login_close_before_authentication_does_not_replace_valid_session(tmp_path, monkeypatch):
    root = _storage(tmp_path, monkeypatch)
    target = backend.session_state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    prior = {"cookies": [{"name": "SID", "value": "prior", "domain": ".youtube.com"}, {"name": "HSID", "value": "h", "domain": ".youtube.com"}, {"name": "SSID", "value": "s", "domain": ".youtube.com"}]}
    target.write_text(json.dumps(prior), encoding="utf-8")

    class Page:
        url = "https://accounts.google.com/"

        def goto(self, *args, **kwargs):
            pass

        def is_closed(self):
            return True

    class Context:
        def new_page(self):
            return Page()

        def close(self):
            pass

    class Browser:
        def new_context(self):
            return Context()

        def close(self):
            pass

    monkeypatch.setattr(backend, "has_gui_environment", lambda: True)
    monkeypatch.setattr(backend, "launch_browser", lambda *args, **kwargs: Browser())
    result = backend.login_youtube_session(browser_type="firefox")
    assert result["success"] is False
    assert json.loads(target.read_text(encoding="utf-8")) == prior
    assert not list(target.parent.glob(".storage_state.*.tmp.json"))


def test_checkpoint_is_atomic_and_task_id_is_sanitized(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    path = backend.write_checkpoint("task/unsafe", "upload_started", route="social-auto-upload")
    assert path.name == "task_unsafe.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "upload_started"
    assert payload["task_id"] == "task/unsafe"


def test_interrupted_upload_checkpoint_blocks_task_until_manual_verification(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [{"id": "task_crashed", "state": "doing", "stage": "upload"}])
    backend.write_checkpoint("task_crashed", "upload_started", route="social-auto-upload")

    recovered = backend.reconcile_uncertain_uploads()

    task = storage.read_json("tasks.json")[0]
    checkpoint = json.loads(backend.checkpoint_path("task_crashed").read_text(encoding="utf-8"))
    assert recovered == ["task_crashed"]
    assert task["state"] == "blocked"
    assert task["stop_reason"] == "upload_uncertain"
    assert task["upload_uncertain"] is True
    assert checkpoint["status"] == "upload_uncertain"


def test_exception_after_file_transfer_started_is_marked_uncertain(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    session = backend.session_state_path()
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(json.dumps({"cookies": [{"name": "SID", "value": "session", "domain": ".youtube.com"}, {"name": "HSID", "value": "h", "domain": ".youtube.com"}, {"name": "SSID", "value": "s", "domain": ".youtube.com"}]}), encoding="utf-8")
    trace = backend._UploadTrace()
    trace.file_upload_started = True

    async def fail_after_upload(**kwargs):
        error = RuntimeError("network timeout after transfer")
        error._social_auto_upload_trace = trace
        raise error

    monkeypatch.setattr(backend, "_run_upstream_upload", fail_after_upload)
    monkeypatch.setattr(backend, "get_active_proxy", lambda: None)

    result = backend.upload_youtube_video(task_id="task_timeout", video_path="video.mp4", title="Title", browser_type="chromium")

    checkpoint = json.loads(backend.checkpoint_path("task_timeout").read_text(encoding="utf-8"))
    assert result.ok is False
    assert result.data["reason"] == "upload_uncertain"
    assert checkpoint["status"] == "upload_uncertain"


def test_runtime_conf_provisioning_enables_real_upstream_import():
    """1.0.06 (PARTE 0): regressão do `No module named 'conf'` da Rota A.

    O sdist pinned não instala `conf.py`; o import in-process de
    `uploader.youtube_uploader.main` fazia TODOS os uploads directos YouTube
    falharem. Com o pacote instalado (dev), o provisionamento in-process tem
    de tornar o import REAL possível — sem monkeypatch. No CI empírico
    (requirements-dev sem o pacote pesado), o contrato mínimo: falhar com a
    mensagem descritiva, nunca ModuleNotFoundError cru.
    """
    if backend._installed_upstream_root() is None:
        with pytest.raises(RuntimeError, match="social-auto-upload"):
            backend._ensure_upstream_runtime_conf()
        return
    base = backend._ensure_upstream_runtime_conf()
    # O upstream injecta BASE_DIR/utils/stealth.min.js via set_init_script:
    # o provisionamento tem de o garantir no base dir.
    assert (base / "utils" / "stealth.min.js").is_file()
    from uploader.youtube_uploader.main import YouTubeVideo

    assert YouTubeVideo.__name__ == "YouTubeVideo"


def _write_direct_youtube_session(monkeypatch, tmp_path):
    _storage(tmp_path, monkeypatch)
    session = backend.session_state_path()
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(
        json.dumps({"cookies": [{"name": "SID", "value": "direct-session", "domain": ".youtube.com"}, {"name": "HSID", "value": "h", "domain": ".youtube.com"}, {"name": "SSID", "value": "s", "domain": ".youtube.com"}]}),
        encoding="utf-8",
    )
    return session


def _valid_cli_result(args, **kwargs):
    return {"status": "ok", "returncode": 0, "stdout": "ok", "stderr": "", "message": "ok"}


def test_check_youtube_session_inherits_direct_session_without_cli_login(tmp_path, monkeypatch):
    """1.0.06 (PARTE 2): a conta CLI youtube herda a sessão da UI (Rota A)."""
    _write_direct_youtube_session(monkeypatch, tmp_path)
    cookie = backend.get_sau_cookie_path("youtube", "minhaconta")
    monkeypatch.setattr(backend, "_run_sau_cli", _valid_cli_result)

    result = backend.check_platform_session("youtube", "minhaconta")

    assert result["valid"] is True
    assert cookie.is_file()
    assert json.loads(cookie.read_text(encoding="utf-8"))["cookies"][0]["value"] == "direct-session"


def test_check_youtube_session_preserves_fresher_cli_login(tmp_path, monkeypatch):
    """Um login CLI próprio (mais recente) nunca é sobrescrito pela herança."""
    _write_direct_youtube_session(monkeypatch, tmp_path)
    cookie = backend.get_sau_cookie_path("youtube", "minhaconta")
    cookie.parent.mkdir(parents=True, exist_ok=True)
    cookie.write_text(
        json.dumps({"cookies": [{"name": "SID", "value": "cli-login", "domain": ".youtube.com"}, {"name": "HSID", "value": "h", "domain": ".youtube.com"}, {"name": "SSID", "value": "s", "domain": ".youtube.com"}]}),
        encoding="utf-8",
    )
    future = time.time() + 100
    os.utime(cookie, (future, future))
    monkeypatch.setattr(backend, "_run_sau_cli", _valid_cli_result)

    result = backend.check_platform_session("youtube", "minhaconta")

    assert result["valid"] is True
    assert json.loads(cookie.read_text(encoding="utf-8"))["cookies"][0]["value"] == "cli-login"


def test_check_youtube_session_without_direct_session_reports_missing_cookie(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    result = backend.check_platform_session("youtube", "minhaconta")
    assert result["valid"] is False
    assert result["status"] == "missing"
    assert not backend.get_sau_cookie_path("youtube", "minhaconta").exists()


def test_non_youtube_platforms_do_not_inherit_the_direct_session(tmp_path, monkeypatch):
    _write_direct_youtube_session(monkeypatch, tmp_path)

    result = backend.check_platform_session("douyin", "minhaconta")

    # A sessão directa é só de YouTube: nenhuma outra plataforma a herda.
    assert result["valid"] is False
    assert result["status"] == "missing"
    assert not backend.get_sau_cookie_path("douyin", "minhaconta").exists()
