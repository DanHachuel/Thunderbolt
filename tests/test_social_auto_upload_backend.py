from __future__ import annotations

import json

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
    state.write_text(json.dumps({"cookies": [{"name": "SID", "value": "session", "domain": ".youtube.com"}]}), encoding="utf-8")
    assert backend.validate_storage_state(state, "youtube.com")[0] is True
    assert backend.validate_storage_state(state, "tiktok.com")[0] is False
    assert backend.session_cookies_for_domain({"cookies": [{"name": "SID", "value": "session", "domain": "studio.youtube.com"}]})
    assert not backend.session_cookies_for_domain({"cookies": [{"name": "SID", "value": "session", "domain": "evilnotyoutube.com"}]})


def test_login_close_before_authentication_does_not_replace_valid_session(tmp_path, monkeypatch):
    root = _storage(tmp_path, monkeypatch)
    target = backend.session_state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    prior = {"cookies": [{"name": "SID", "value": "prior", "domain": ".youtube.com"}]}
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
    session.write_text(json.dumps({"cookies": [{"name": "SID", "value": "session", "domain": ".youtube.com"}]}), encoding="utf-8")
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
