from __future__ import annotations

import json
import os
from types import SimpleNamespace

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


def _video(tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"video-bytes")
    return path


def test_platform_matrix_lists_upstream_platforms_and_excludes_tiktok():
    rows = backend.get_platform_uploaders()
    platforms = {row["platform"] for row in rows}
    assert {"douyin", "kuaishou", "xiaohongshu", "bilibili", "tencent", "baijiahao", "alipay", "weibo", "hupu", "youtube"} <= platforms
    assert "tiktok" not in platforms
    assert next(row for row in rows if row["platform"] == "bilibili")["login_mode"] == "terminal"
    assert "tiktok" in backend.SAU_UNSUPPORTED_PLATFORMS


def test_accounts_are_saved_as_metadata_and_cookie_path_is_confined(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    account = backend.add_sau_account("douyin", "channel_1", "Canal principal")
    assert account == {"platform": "douyin", "account_name": "channel_1", "label": "Canal principal"}
    assert backend.list_sau_accounts("douyin") == [account]
    assert backend.get_sau_cookie_path("douyin", "channel_1") == (
        storage.STORAGE / "state" / "social_auto_upload" / "cookies" / "douyin_channel_1.json"
    )
    settings = storage.read_json("settings.json", {})
    assert settings["sau_accounts"] == [account]
    with pytest.raises(ValueError):
        backend.add_sau_account("douyin", "../outside")


def test_runtime_conf_uses_base_dir_instead_of_unsupported_environment_variables(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    env, runtime = backend._sau_environment()
    config = (runtime / "conf.py").read_text(encoding="utf-8")
    assert "BASE_DIR = Path(" in config
    # No Windows o caminho no conf.py aparece com barras invertidas; normalizar
    # ambos os lados mantém a asserção multiplataforma.
    assert str(backend.session_directory()).replace("\\", "/") in config.replace("\\\\", "/").replace("\\", "/")
    assert "YT_PROXY = None" in config
    assert str(runtime) in env["PYTHONPATH"].split(os.pathsep)
    assert "BASE_DIR" not in env
    assert not any(key.startswith("SAU_") or key == "CAMOUFOX_HEADLESS" for key in env)


def test_run_sau_cli_uses_argv_runtime_and_sanitised_output(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    monkeypatch.setattr(backend, "_sau_command_prefix", lambda: ["sau-test"])
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='cookie=secret-value\n{"SESSDATA":"json-secret","access_token":"token-secret"}\nready', stderr="")

    monkeypatch.setattr(backend.subprocess, "run", fake_run)
    result = backend._run_sau_cli(["douyin", "check", "--account", "channel_1"], timeout_seconds=15)
    assert result["status"] == "ok"
    assert seen["command"] == ["sau-test", "douyin", "check", "--account", "channel_1"]
    assert not seen.get("shell", False)
    assert "cookie=***" in result["stdout"]
    assert "secret-value" not in result["stdout"]
    assert "json-secret" not in result["stdout"]
    assert "token-secret" not in result["stdout"]
    assert (storage.STORAGE / "state" / "social_auto_upload" / "runtime" / "conf.py").is_file()


def test_login_uses_headed_mode_and_restores_partial_cookie_on_timeout(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    monkeypatch.setattr(backend, "get_sau_install_status", lambda: {"installed": True, "status": "installed"})
    monkeypatch.setattr(backend, "has_gui_environment", lambda: True)
    cookie = backend.get_sau_cookie_path("douyin", "channel_1")
    cookie.parent.mkdir(parents=True, exist_ok=True)
    cookie.write_text('{"cookies":[{"name":"prior"}]}', encoding="utf-8")
    captured = {}

    def fake_run(args, *, timeout_seconds):
        captured.update({"args": args, "timeout": timeout_seconds})
        cookie.write_text('{"cookies":[{"name":"partial"}]}', encoding="utf-8")
        return {"status": "timeout", "message": "timed out", "stdout": "", "stderr": ""}

    monkeypatch.setattr(backend, "_run_sau_cli", fake_run)
    result = backend.login_platform("douyin", "channel_1", timeout_seconds=800)
    assert captured["args"] == ["douyin", "login", "--account", "channel_1", "--headed"]
    assert 1 <= captured["timeout"] <= 300
    assert result["status"] == "timeout"
    assert "prior" in cookie.read_text(encoding="utf-8")


def test_upload_uses_headless_cli_and_writes_confirmed_checkpoint(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    video = _video(tmp_path)
    monkeypatch.setattr(backend, "get_sau_install_status", lambda: {"installed": True, "status": "installed"})
    monkeypatch.setattr(backend, "check_platform_session", lambda *args: {"valid": True, "status": "valid", "message": "ok"})
    calls = []

    def fake_run(args, *, timeout_seconds):
        calls.append((args, timeout_seconds))
        return {"status": "ok", "returncode": 0, "stdout": "Upload concluído", "stderr": "", "message": "Upload concluído"}

    monkeypatch.setattr(backend, "_run_sau_cli", fake_run)
    result = backend.upload_video_via_sau(
        task_id="task_1", platform="douyin", account_name="channel_1", video_path=video,
        title="Título", description="Descrição", tags=["tag1", "tag2"], timeout_seconds=600,
    )
    args, timeout = calls[0]
    assert args[:6] == ["douyin", "upload-video", "--account", "channel_1", "--file", str(video.resolve())]
    assert "--headless" in args
    assert "--tags" in args and "tag1,tag2" in args
    assert timeout == 600
    assert result.ok is True
    assert result.data["backend"] == "sau-cli + patchright/chromium"
    checkpoint = backend.get_sau_upload_checkpoint(result.data["checkpoint_id"])
    assert checkpoint["status"] == "upload_confirmed"
    assert checkpoint["task_id"] == "task_1"


def test_bilibili_upload_requires_tid_and_does_not_pass_unsupported_headless_flag(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    video = _video(tmp_path)
    monkeypatch.setattr(backend, "get_sau_install_status", lambda: {"installed": True, "status": "installed"})
    monkeypatch.setattr(backend, "check_platform_session", lambda *args: {"valid": True, "status": "valid"})
    calls = []
    monkeypatch.setattr(backend, "_run_sau_cli", lambda args, **kwargs: (calls.append(args) or {"status": "ok", "returncode": 0, "stdout": "done", "stderr": "", "message": "done"}))
    result = backend.upload_video_via_sau(task_id="task_bili", platform="bilibili", account_name="creator", video_path=video, title="Vídeo", description="Descrição")
    assert result.ok
    assert "--tid" in calls[0]
    assert "249" in calls[0]
    assert "--headless" not in calls[0]


def test_bilibili_login_uses_interactive_terminal_without_browser_flags(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    monkeypatch.setattr(backend, "get_sau_install_status", lambda: {"installed": True, "status": "installed"})
    monkeypatch.setattr(backend, "_sau_command_prefix", lambda: ["sau-test"])
    captured = {}

    def launch(command, *, runtime, env):
        captured.update({"command": command, "runtime": runtime, "env": env})
        return {"success": True, "status": "terminal_opened", "message": "terminal opened"}

    monkeypatch.setattr(backend, "_launch_bilibili_login", launch)
    result = backend.login_platform("bilibili", "creator")
    assert result["success"] is True
    assert captured["command"] == ["sau-test", "bilibili", "login", "--account", "creator"]
    assert "--headed" not in captured["command"]
    assert result["cookie_path"].replace("\\", "/").endswith("cookies/bilibili_creator.json")


def test_cli_upload_failure_is_uncertain_and_manual_verification_is_required(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    video = _video(tmp_path)
    storage.write_json("tasks.json", [{"id": "task_uncertain", "state": "done", "stage": "ready_upload", "artifacts": {"video": str(video)}}])
    monkeypatch.setattr(backend, "get_sau_install_status", lambda: {"installed": True, "status": "installed"})
    monkeypatch.setattr(backend, "check_platform_session", lambda *args: {"valid": True, "status": "valid"})
    monkeypatch.setattr(backend, "_run_sau_cli", lambda *args, **kwargs: {"status": "failed", "returncode": 1, "stdout": "", "stderr": "network interrupted", "message": "network interrupted"})
    result = backend.upload_video_via_sau(task_id="task_uncertain", platform="douyin", account_name="creator", video_path=video, title="Vídeo")
    assert result.ok is False
    assert result.data["reason"] == "upload_uncertain"
    assert backend.get_sau_upload_checkpoint(result.data["checkpoint_id"])["status"] == "upload_uncertain"
    task = storage.read_json("tasks.json")[0]
    assert task["state"] == "blocked"
    assert task["stop_reason"] == "upload_uncertain"
    with pytest.raises(ValueError):
        backend.confirm_sau_upload_not_published(result.data["checkpoint_id"], "task_uncertain")
    assert backend.confirm_sau_upload_not_published(result.data["checkpoint_id"], "task_uncertain", manual_confirmation=True)
    task = storage.read_json("tasks.json")[0]
    assert task["state"] == "done"
    assert task["upload_uncertain"] is False
    assert backend.get_sau_upload_checkpoint(result.data["checkpoint_id"])["status"] == "upload_failed_clean"


def test_interrupted_cli_operation_reconciles_the_original_checkpoint(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    operation_id = "sau-task_1-douyin-0123456789abcdef"
    storage.write_json("tasks.json", [{"id": "task_1", "state": "doing", "stage": "upload"}])
    checkpoint = backend._write_sau_checkpoint(operation_id, "upload_started", task_id="task_1", route="social-auto-upload-cli", platform="douyin")
    assert backend.reconcile_uncertain_uploads() == ["task_1"]
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["status"] == "upload_uncertain"
    assert payload["task_id"] == "task_1"


def test_checkpoint_identity_does_not_change_when_video_is_renamed(tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "renamed.mp4"
    first.write_bytes(b"same content")
    second.write_bytes(b"same content")
    assert backend.sau_upload_checkpoint_id("task_1", "douyin", "creator", first) == backend.sau_upload_checkpoint_id("task_1", "douyin", "creator", second)


def test_tiktok_is_rejected_without_trying_to_bypass_upstream(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    video = _video(tmp_path)
    result = backend.upload_video_via_sau(task_id="task_tiktok", platform="tiktok", account_name="creator", video_path=video, title="Vídeo")
    assert result.ok is False
    assert result.data["reason"] == "invalid_configuration"
    assert "não é suportado" in result.message


def test_cli_install_status_rejects_python_313(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    class VersionInfo313:
        major, minor, micro = 3, 13, 0

        def __ge__(self, other):
            return (self.major, self.minor, self.micro) >= other

        def __lt__(self, other):
            return (self.major, self.minor, self.micro) < other

    version_info = VersionInfo313()
    monkeypatch.setattr(backend.sys, "version_info", version_info)
    result = backend.get_sau_install_status()
    assert result["installed"] is False
    assert result["status"] == "error"
    assert "<3.13" in result["message"]
