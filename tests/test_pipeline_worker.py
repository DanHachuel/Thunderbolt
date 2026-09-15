from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tomllib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_ui.thumbnail_generation import ThumbnailGenerationError

from hermes_ui import storage
from hermes_ui import pipeline_worker


def _isolate_storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", root / "tiktok" / "prompts_master")
    monkeypatch.setattr(storage, "MEDIA_DOWNLOADS", root / "downloads")
    monkeypatch.setattr(pipeline_worker, "STORAGE", root)
    storage.ensure_storage()
    return root


def test_pipeline_lock_recovers_after_dead_process(tmp_path, monkeypatch):
    root = _isolate_storage(tmp_path, monkeypatch)
    lock_path = root / "state" / pipeline_worker.PIPELINE_LOCK_FILENAME
    lock_path.write_text("999999999", encoding="utf-8")

    acquired = pipeline_worker._acquire_lock()

    assert acquired == lock_path
    assert lock_path.read_text(encoding="utf-8") == str(__import__("os").getpid())
    lock_path.unlink()


def test_recover_stale_task_marks_it_failed(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    old_timestamp = (datetime.now(timezone.utc) - timedelta(seconds=pipeline_worker.STALE_TASK_SECONDS + 10)).isoformat()
    storage.write_json(
        "tasks.json",
        [{
            "id": "video_stale",
            "state": "doing",
            "stage": "video",
            "progress": 72,
            "title": "Vídeo preso",
            "channel_name": "Canal",
            "updated_at": old_timestamp,
        }],
    )

    recovered = pipeline_worker.recover_stale_tasks()

    task = storage.read_json("tasks.json")[0]
    assert recovered == ["video_stale"]
    assert task["state"] == "failed"
    assert task["failed_stage"] == "video"
    assert "heartbeat" in task["error"]


def test_manual_saved_script_is_not_selected_until_start(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    tasks = [
        {"id": "saved-script", "state": "to_do", "manual_start_required": True},
        {"id": "automatic-task", "state": "to_do", "manual_start_required": False},
    ]

    assert pipeline_worker._next_runnable_task(tasks)["id"] == "automatic-task"
    tasks[0]["state"] = "doing"
    assert pipeline_worker._next_runnable_task(tasks)["id"] == "saved-script"


def test_run_task_reuses_prepared_title_and_thumbnail_without_full_creative_generation(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    video_path = tmp_path / "prepared.mp4"
    video_path.write_bytes(b"mp4")
    task = {
        "id": "video_prepared",
        "state": "to_do",
        "stage": "script",
        "progress": 0,
        "topic": "Tema preparado",
        "topic_source": "manual",
        "title": "Título preparado",
        "thumbnail_variant": {
            "concept": "Conceito preparado",
            "image_prompt": "prompt preparado",
            "overlay_text": "TEMA REAL",
            "lettering_prompt": "texto grande",
        },
        "thumbnail_variants": [{"concept": "Conceito preparado", "image_prompt": "prompt preparado", "overlay_text": "TEMA REAL", "lettering_prompt": "texto grande"}],
        "generation_settings": {"video_script": "Roteiro preparado", "video_keywords": "alpha, beta"},
        "channel_id": "channel-1",
        "language": "pt-BR",
    }
    channel = {"id": "channel-1", "name": "Canal teste", "language": "pt-BR", "niche": "Teste"}
    blueprint = {"id": "blueprint-1", "name": "Blueprint teste"}
    updates = []

    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {"youtube_batch_accounts": []})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: blueprint)
    monkeypatch.setattr(pipeline_worker, "_update", lambda task_id, **changes: updates.append(changes) or {**task, **changes})
    monkeypatch.setattr(pipeline_worker, "save_script_document", lambda script: {"path": "prepared-script.md"})
    monkeypatch.setattr(pipeline_worker, "_save_json_artifact", lambda task_id, name, payload: f"{name}.json")
    monkeypatch.setattr(pipeline_worker, "generate_thumbnail_image", lambda *args, **kwargs: tmp_path / "prepared.jpg")
    monkeypatch.setattr(pipeline_worker, "_run_video_helper", lambda value: video_path)
    monkeypatch.setattr(pipeline_worker, "upload_with_default_route", lambda *args, **kwargs: SimpleNamespace(ok=True, message="", data={"uploaded": True}))
    monkeypatch.setattr(pipeline_worker, "generate_creative_package", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deve regenerar o pacote criativo")))

    result = pipeline_worker._run_task(task)

    assert result["state"] == "done"
    assert result["title"] == "Título preparado"
    assert any(update.get("thumbnail_prompt") == "prompt preparado" and update.get("thumbnail_text") == "TEMA REAL" for update in updates)
    assert any(update.get("stage") == "upload" and update.get("state") == "done" for update in updates)


def test_existing_thumbnail_path_is_reused_from_pipeline_artifacts(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    thumbnail = tmp_path / "thumbnail-pipeline.jpg"
    thumbnail.write_bytes(b"thumbnail")
    task = {
        "thumbnail_path": str(thumbnail),
        "thumbnail_variant": {"image_path": str(thumbnail)},
        "thumbnail_variants": [{"image_path": str(thumbnail)}],
    }

    monkeypatch.setattr(
        pipeline_worker,
        "_generate_pipeline_thumbnail",
        lambda *args, **kwargs: pytest.fail("não deve regenerar thumbnail existente"),
    )

    assert pipeline_worker._existing_thumbnail_path(task, {}, task["thumbnail_variant"]) == thumbnail


def test_retried_video_uses_settings_reloaded_at_execution_time(tmp_path, monkeypatch):
    """A tarefa preserva o conteúdo, mas entrega a configuração actual ao provider."""
    _isolate_storage(tmp_path, monkeypatch)
    task = {
        "id": "video_retry_current_config",
        "state": "to_do",
        "stage": "video",
        "progress": 56,
        "topic": "Tema para retoma",
        "topic_source": "manual",
        "title": "Título pronto",
        "tags": ["tema", "retoma"],
        "style_wide": "full_ia",
        "language": "pt-BR",
        "generation_settings": {
            "video_script": "Roteiro preservado",
            "media_provider_priority": ["provider_antigo"],
        },
        "thumbnail_variant": {"image_prompt": "Thumbnail pronta", "overlay_text": "RETOMA"},
        "artifacts": {},
    }
    current_settings = {"media_provider_priority": ["provider_actual"], "youtube_batch_accounts": []}
    captured_settings = []
    video_path = tmp_path / "current-provider-video.mp4"
    video_path.write_bytes(b"mp4")
    thumbnail_path = tmp_path / "current-provider-thumbnail.jpg"
    thumbnail_path.write_bytes(b"jpg")

    monkeypatch.setattr(pipeline_worker, "_settings", lambda: current_settings)
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "_update", lambda task_id, **changes: {**task, **changes})
    monkeypatch.setattr(pipeline_worker, "_save_json_artifact", lambda task_id, name, payload: f"{name}.json")
    monkeypatch.setattr(
        pipeline_worker,
        "generate_video_from_pool",
        lambda settings, *args, **kwargs: captured_settings.append(settings) or video_path,
    )
    monkeypatch.setattr(pipeline_worker, "_generate_pipeline_thumbnail", lambda *args, **kwargs: thumbnail_path)

    result = pipeline_worker._run_task(task)

    assert captured_settings == [current_settings]
    assert captured_settings[0]["media_provider_priority"] == ["provider_actual"]
    assert result["state"] == "done"


def test_run_task_resumes_from_persisted_artifacts_without_regenerating_previous_stages(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    script_path = tmp_path / "roteiro-pronto.md"
    script_path.write_text("---\nid: script-ready\ntype: video_script\n---\n\nRoteiro persistido", encoding="utf-8")
    video_path = tmp_path / "video-pronto.mp4"
    video_path.write_bytes(b"mp4")
    thumbnail_path = tmp_path / "thumbnail-pronta.jpg"
    thumbnail_path.write_bytes(b"jpg")
    prompt_path = tmp_path / "thumbnail-prompt.json"
    prompt_path.write_text('{"thumbnail": {"image_prompt": "prompt persistido", "overlay_text": "PRONTO"}}', encoding="utf-8")
    task = {
        "id": "video_resume",
        "state": "failed",
        "stage": "thumbnail",
        "progress": 86,
        "topic": "Tema retomado",
        "topic_source": "manual",
        "title": "Título persistido",
        "tags": ["tema", "retomado"],
        "channel_id": "channel-resume",
        "language": "pt-BR",
        "artifacts": {
            "script": str(script_path),
            "video": str(video_path),
            "thumbnail": str(thumbnail_path),
            "thumbnail_prompt_json": str(prompt_path),
        },
        "thumbnail_variant": {"image_prompt": "prompt persistido", "overlay_text": "PRONTO"},
        "thumbnail_prompt": "prompt persistido",
        "thumbnail_text": "PRONTO",
    }
    channel = {"id": "channel-resume", "name": "Canal retomado", "language": "pt-BR", "niche": "Teste", "google_account_id": "account-resume"}
    storage.write_json("channels.json", [channel])
    storage.write_json("tasks.json", [task])
    calls = {"upload": 0}

    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {"youtube_batch_accounts": [{"id": "account-resume"}]})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "save_script_document", lambda *args, **kwargs: pytest.fail("não deve guardar novamente o roteiro"))
    monkeypatch.setattr(pipeline_worker, "generate_script_document", lambda *args, **kwargs: pytest.fail("não deve regenerar o roteiro"))
    monkeypatch.setattr(pipeline_worker, "generate_title_and_keywords", lambda *args, **kwargs: pytest.fail("não deve regenerar título e keywords"))
    monkeypatch.setattr(pipeline_worker, "_run_video_helper", lambda *args, **kwargs: pytest.fail("não deve regenerar o vídeo"))
    monkeypatch.setattr(pipeline_worker, "generate_video_from_pool", lambda *args, **kwargs: pytest.fail("não deve chamar o pool de vídeo"))
    monkeypatch.setattr(pipeline_worker, "generate_thumbnail_prompt", lambda *args, **kwargs: pytest.fail("não deve regenerar o prompt da thumbnail"))
    monkeypatch.setattr(pipeline_worker, "_generate_pipeline_thumbnail", lambda *args, **kwargs: pytest.fail("não deve regenerar a thumbnail pronta"))

    def fake_upload(*args, **kwargs):
        calls["upload"] += 1
        assert kwargs["video_path"] == str(video_path)
        assert kwargs["thumbnail_path"] == str(thumbnail_path)
        return SimpleNamespace(ok=True, message="", data={"uploaded": True})

    monkeypatch.setattr(pipeline_worker, "upload_with_default_route", fake_upload)

    result = pipeline_worker._run_task(task)

    persisted = storage.read_json("tasks.json")[0]
    assert result["state"] == "done"
    assert persisted["stage"] == "upload"
    assert persisted["state"] == "done"
    assert persisted["artifacts"]["video"] == str(video_path)
    assert persisted["artifacts"]["thumbnail"] == str(thumbnail_path)
    assert calls["upload"] == 1


def test_run_task_completes_locally_when_no_upload_route_is_configured(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    script_path = tmp_path / "roteiro-pronto.md"
    script_path.write_text("Roteiro persistido", encoding="utf-8")
    video_path = tmp_path / "video-pronto.mp4"
    video_path.write_bytes(b"mp4")
    thumbnail_path = tmp_path / "thumbnail-pronta.jpg"
    thumbnail_path.write_bytes(b"jpg")
    prompt_path = tmp_path / "thumbnail-prompt.json"
    prompt_path.write_text('{"thumbnail": {"image_prompt": "prompt persistido", "overlay_text": "PRONTO"}}', encoding="utf-8")
    task = {
        "id": "video_local_ready",
        "state": "failed",
        "stage": "upload",
        "progress": 94,
        "topic": "Tema pronto",
        "title": "Título pronto",
        "channel_id": "channel-local",
        "thumbnail_variant": {"image_prompt": "prompt persistido", "overlay_text": "PRONTO"},
        "artifacts": {
            "script": str(script_path),
            "video": str(video_path),
            "thumbnail": str(thumbnail_path),
            "thumbnail_prompt_json": str(prompt_path),
        },
    }
    channel = {"id": "channel-local", "name": "Canal local", "language": "en"}
    storage.write_json("tasks.json", [task])
    monkeypatch.setattr(
        pipeline_worker,
        "_settings",
        lambda: {"youtube_batch_accounts": [], "upload_post_enabled": False, "upload_post_auto_upload": False, "postiz_enabled": False, "postiz_auto_publish": False},
    )
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "upload_with_default_route", lambda *args, **kwargs: pytest.fail("não deve tentar publicação sem rota configurada"))

    result = pipeline_worker._run_task(task)

    persisted = storage.read_json("tasks.json")[0]
    assert result["state"] == "done"
    assert persisted["stage"] == "upload"
    assert persisted["artifacts"]["upload"]["route"] == "local"
    assert persisted["artifacts"]["upload"]["status"] == "skipped"


def test_run_once_marks_unexpected_pipeline_error_terminal(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [{"id": "video_error", "state": "to_do", "stage": "script", "progress": 0, "title": "Erro", "channel_name": "Canal"}])
    monkeypatch.setattr(pipeline_worker, "_run_task", lambda task: (_ for _ in ()).throw(RuntimeError("falha simulada")))

    result = pipeline_worker.run_once()

    assert result["ok"] is False
    task = storage.read_json("tasks.json")[0]
    assert task["state"] == "failed"
    assert task["error"].startswith("falha simulada")
    assert "API/provider:" in task["error"]
    assert task["failure_api"] == "OpenAI / NVIDIA NIM API"
    assert storage.read_json(pipeline_worker.PIPELINE_LOG_FILENAME)["status"] == "failed"
    from hermes_ui.logs import list_logs
    from hermes_ui.notifications import list_notifications
    assert list_notifications()[0]["metadata"]["failure_api"] == "OpenAI / NVIDIA NIM API"
    assert next(item for item in list_logs() if item["task_id"] == "video_error")["api_provider"] == "OpenAI / NVIDIA NIM API"


def test_run_once_persists_idle_heartbeat(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)

    result = pipeline_worker.run_once()
    status = pipeline_worker.load_pipeline_worker_status()

    assert result["status"] == "idle"
    assert status["status"] == "idle"
    assert status["alive"] is True
    assert status["last_heartbeat_at"]


def test_upload_with_heartbeat_refreshes_worker_and_task_until_completion(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [{"id": "upload-long", "state": "doing", "stage": "upload", "progress": 94}])
    monkeypatch.setattr(pipeline_worker, "UPLOAD_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    worker_heartbeats: list[dict] = []
    monkeypatch.setattr(pipeline_worker, "_worker_heartbeat", lambda **updates: worker_heartbeats.append(updates))
    release = threading.Event()

    result = pipeline_worker._upload_with_heartbeat(
        "upload-long",
        lambda: (release.wait(0.18), {"ok": True})[1],
    )

    assert result == {"ok": True}
    assert len(worker_heartbeats) >= 2
    assert all(item["stage"] == "upload" and item["status"] == "running" for item in worker_heartbeats)
    task = storage.read_json("tasks.json")[0]
    assert task["upload_status"] == "running"
    assert task["upload_heartbeat_at"]
    assert task["upload_elapsed_seconds"] >= 0


def test_upload_with_heartbeat_propagates_provider_exception(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [{"id": "upload-error", "state": "doing", "stage": "upload", "progress": 94}])

    def fail_upload():
        raise RuntimeError("falha do provider")

    with pytest.raises(RuntimeError, match="falha do provider"):
        pipeline_worker._upload_with_heartbeat("upload-error", fail_upload)


def test_backlog_has_live_progress_and_stale_recovery_ui():
    source = Path(__file__).resolve().parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")

    assert "@st.fragment(run_every=5.0)\ndef _render_pipeline_progress_panel()" in source
    assert "st.progress(progress, text=f\"{label} · {_pipeline_stage_label(task)} · {progress}%\")" in source
    assert "recover_stale_tasks()" in source
    assert "_render_pipeline_progress_panel()" in source
    assert "Worker de vídeo sem heartbeat recente" in source
    assert 'st.rerun(scope="app")' not in source


def test_worker_progress_is_monotonic_when_resuming_old_checkpoints():
    source = Path(__file__).resolve().parents[1].joinpath("hermes_ui", "pipeline_worker.py").read_text(encoding="utf-8")

    assert 'updates["progress"] = max(previous_progress, requested_progress)' in source
    assert "Nunca deixar a percentagem persistida recuar" in source


def test_stock_video_uses_total_timeout_instead_of_false_idle_watchdog(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    settings = {"video_source": "pixabay"}
    task = {"style_wide": "pixabay", "video_script": "roteiro curto"}

    assert pipeline_worker._video_timeout_seconds(task, settings) == pipeline_worker.LONG_STOCK_VIDEO_TIMEOUT_SECONDS
    assert pipeline_worker._video_idle_timeout_seconds(task, settings) == pipeline_worker.STOCK_VIDEO_IDLE_TIMEOUT_SECONDS


def test_non_stock_video_keeps_idle_watchdog(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    task = {"style_wide": "full_ia", "video_script": "roteiro curto"}

    assert pipeline_worker._video_idle_timeout_seconds(task, {}) == pipeline_worker.VIDEO_IDLE_TIMEOUT_SECONDS


class _FakeStdout:
    def __init__(self, lines):
        self._lines = iter(lines)

    def readline(self):
        return next(self._lines, "")

    def close(self):
        return None


class _FakePopen:
    def __init__(self, lines, returncode=0, stays_alive=False):
        self.stdout = _FakeStdout(lines)
        self.returncode = None if stays_alive else returncode
        self._stays_alive = stays_alive

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9
        self._stays_alive = False

    def wait(self, timeout=None):
        return self.returncode


def test_video_helper_uses_configured_root_and_persists_helper_diagnostics(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "cli.py").write_text("# fake", encoding="utf-8")
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    video_path = tmp_path / "generated.mp4"
    video_path.write_bytes(b"mp4")
    storage.write_json("settings.json", {"moneyprinter_path": str(root), "pexels_api_keys": ["pexels-test-key"]})
    storage.write_json("tasks.json", [{"id": "video_root", "state": "doing", "stage": "video", "progress": 68, "topic": "Tema"}])
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return _FakePopen([
            f"VIDEO_FILE={video_path}\n",
            "LOG_FILE=/tmp/mpt-video.log\n",
            "RESULT_FILE=/tmp/mpt-result.json\n",
        ])

    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", fake_popen)

    result = pipeline_worker._run_video_helper({"id": "video_root", "topic": "Tema"})

    assert result == video_path
    assert captured["command"][captured["command"].index("--root") + 1] == str(root.resolve())
    task = storage.read_json("tasks.json")[0]
    diagnostics_path = Path(task["artifacts"]["video_diagnostics"])
    diagnostics = __import__("json").loads(diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics["log_file"] == "/tmp/mpt-video.log"
    assert task["video_log"] == "/tmp/mpt-video.log"
    assert task["video_result"] == "/tmp/mpt-result.json"
    assert "VIDEO_FILE=" in diagnostics["output_tail"]


def test_video_helper_reports_each_missing_moneyprinter_api(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "cli.py").write_text("# fake", encoding="utf-8")
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    storage.write_json("settings.json", {"moneyprinter_path": str(root), "pexels_api_keys": ["pexels-test-key"]})
    storage.write_json("tasks.json", [{"id": "video-missing-mpt-api", "state": "doing", "stage": "video", "topic": "Tema"}])

    def fake_popen(command, **kwargs):
        return _FakePopen([
            "MPT_NEEDS_INPUT\n",
            "LLM_PROVIDER=openai\n",
            "MISSING=openai_api_key\n",
            "MISSING=pexels_api_keys\n",
        ], returncode=10)

    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", fake_popen)

    with pytest.raises(pipeline_worker.PipelineError, match="OpenAI / NVIDIA NIM API \\+ Pexels API") as raised:
        pipeline_worker._run_video_helper({"id": "video-missing-mpt-api", "topic": "Tema"})

    assert raised.value.failure_metadata["failure_provider"] == "openai, pexels"
    assert raised.value.failure_metadata["failure_config_fields"] == "openai_api_key, pexels_api_keys"


def test_video_helper_forwards_stock_source_and_moneyprinter_options(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "cli.py").write_text("# fake", encoding="utf-8")
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    video_path = tmp_path / "generated.mp4"
    video_path.write_bytes(b"mp4")
    storage.write_json(
        "settings.json",
        {
            "moneyprinter_path": str(root),
            "material_api_keys": {"pixabay": ["pixabay-test-key", "pixabay-second-key"]},
            "azure_speech_key": "azure-test-key",
            "azure_speech_region": "eastus",
        },
    )
    storage.write_json("tasks.json", [{"id": "video_pixabay", "state": "doing", "stage": "video", "progress": 68, "topic": "Tema"}])
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return _FakePopen([f"VIDEO_FILE={video_path}\n"])

    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", fake_popen)
    result = pipeline_worker._run_video_helper(
        {
            "id": "video_pixabay",
            "topic": "Tema",
            "style_wide": "pixabay",
            "language": "pt-BR",
            "format": "wide",
            "video_script": "Roteiro preparado",
            "video_keywords": ["economia", "mercado"],
            "generation_settings": {
                "video_aspect_ratio": "Landscape 16:9",
                "video_concatenation_mode": "Sequential Concatenation",
                "video_transition_mode": "Dissolve",
                "maximum_clip_duration": 8,
                "match_visuals_to_script_order": True,
                "voiceover_mode": "None",
                "enable_subtitles": False,
            },
        }
    )

    assert result == video_path
    command = captured["command"]
    assert command[command.index("--video-source") - 1] == "--"
    assert command[command.index("--video-source") + 1] == "pixabay"
    assert command[command.index("--video-script") + 1] == "Roteiro preparado"
    assert command[command.index("--video-terms") + 1] == "economia,mercado"
    assert command[command.index("--video-aspect") + 1] == "16:9"
    assert command[command.index("--video-concat-mode") + 1] == "sequential"
    assert command[command.index("--video-transition-mode") + 1] == "fade-out"
    assert command[command.index("--video-clip-duration") + 1] == "8"
    assert "--match-materials-to-script" in command
    assert command[command.index("--voice-name") + 1] == "no-voice"
    assert "--no-subtitle-enabled" in command
    assert captured["env"]["MPT_PIXABAY_API_KEY"] == "pixabay-test-key"
    assert captured["env"]["MPT_PIXABAY_API_KEYS"] == '["pixabay-test-key", "pixabay-second-key"]'
    assert captured["env"]["MPT_AZURE_SPEECH_KEY"] == "azure-test-key"
    assert captured["env"]["MPT_AZURE_SPEECH_REGION"] == "eastus"
    config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
    assert config["app"]["pixabay_api_keys"] == ["pixabay-test-key", "pixabay-second-key"]


def test_video_helper_falls_back_from_pexels_to_pixabay_by_priority(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "cli.py").write_text("# fake", encoding="utf-8")
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    video_path = tmp_path / "pixabay-generated.mp4"
    video_path.write_bytes(b"mp4")
    storage.write_json(
        "settings.json",
        {
            "moneyprinter_path": str(root),
            "video_source": "pexels",
            "material_source_cards": [
                {"id": "pexels-primary", "provider": "pexels", "api_key": "pexels-broken", "enabled": True, "priority": 1},
                {"id": "pixabay-fallback", "provider": "pixabay", "api_key": "pixabay-good", "enabled": True, "priority": 2},
            ],
            "material_active_card_id": "pexels-primary",
        },
    )
    storage.write_json("tasks.json", [{"id": "video-stock-fallback", "state": "doing", "stage": "video", "progress": 68, "topic": "Tema"}])
    video_commands = []

    def fake_popen(command, **kwargs):
        video_commands.append((command, kwargs["env"]))
        if len(video_commands) == 1:
            return _FakePopen(["MPT_ERROR=Pexels request failed\n"], returncode=1)
        return _FakePopen([f"VIDEO_FILE={video_path}\n"])

    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", fake_popen)

    result = pipeline_worker._run_video_helper({"id": "video-stock-fallback", "topic": "Tema", "material_source": "pexels"})

    assert result == video_path
    assert [command[command.index("--video-source") + 1] for command, _env in video_commands] == ["pexels", "pixabay"]
    assert video_commands[0][1]["MPT_PEXELS_API_KEY"] == "pexels-broken"
    assert video_commands[0][1].get("MPT_PIXABAY_API_KEY", "") == ""
    assert video_commands[1][1]["MPT_PIXABAY_API_KEY"] == "pixabay-good"
    assert video_commands[1][1].get("MPT_PEXELS_API_KEY", "") == ""


def test_material_video_attempts_rotate_each_prioritized_key_before_next_provider():
    settings = {
        "video_source": "pexels",
        "material_source_cards": [
            {"id": "pexels-1", "provider": "pexels", "api_key": "pexels-one", "enabled": True, "priority": 1},
            {"id": "pexels-2", "provider": "pexels", "api_key": "pexels-two", "enabled": True, "priority": 2},
            {"id": "pixabay-1", "provider": "pixabay", "api_key": "pixabay-one", "enabled": True, "priority": 3},
        ],
    }

    assert pipeline_worker._material_video_attempts({"style_wide": "pexels"}, settings) == [
        ("pexels", "pexels-one"),
        ("pexels", "pexels-two"),
        ("pixabay", "pixabay-one"),
    ]


def test_video_helper_does_not_fallback_when_moneyprinter_reports_llm_credentials(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "cli.py").write_text("# fake", encoding="utf-8")
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    storage.write_json(
        "settings.json",
        {
            "moneyprinter_path": str(root),
            "video_source": "pexels",
            "material_source_cards": [
                {"id": "pexels-primary", "provider": "pexels", "api_key": "pexels-good", "enabled": True, "priority": 1},
                {"id": "pixabay-fallback", "provider": "pixabay", "api_key": "pixabay-good", "enabled": True, "priority": 2},
            ],
        },
    )
    storage.write_json("tasks.json", [{"id": "video-no-llm-fallback", "state": "doing", "stage": "video", "progress": 68, "topic": "Tema"}])
    calls = []

    def fake_popen(command, **kwargs):
        calls.append(command)
        return _FakePopen(["MPT_NEEDS_INPUT\n", "LLM_PROVIDER=openai\n", "MISSING=openai_api_key\n"], returncode=10)

    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", fake_popen)

    with pytest.raises(pipeline_worker.PipelineError, match="OpenAI / NVIDIA NIM API"):
        pipeline_worker._run_video_helper({"id": "video-no-llm-fallback", "topic": "Tema", "material_source": "pexels"})

    assert len(calls) == 1


def test_legacy_azure_tts_v1_uses_sdk_v2_when_credentials_are_configured():
    args = pipeline_worker._moneyprinter_cli_args(
        {
            "topic": "Tema",
            "voice": "en-US-BrianMultilingualNeural-Male",
            "generation_settings": {
                "voiceover_service": "Azure TTS V1",
                "voiceover_mode": "Auto",
            },
        },
        "pexels",
        settings={"azure_speech_key": "configured", "azure_speech_region": "eastus"},
    )
    assert args[args.index("--voice-name") + 1] == "en-US-BrianMultilingualNeural-V2-Male"


def test_edge_tts_timeout_is_attributed_to_azure_speech_api():
    metadata = pipeline_worker._failure_attribution(
        {"style_wide": "pexels"},
        {},
        "video",
        error="azure_tts_v1 - failed, error: edge_tts stream timed out after 30s",
    )
    assert metadata["failure_api"] == "Azure Speech / edge_tts API"
    assert metadata["failure_provider"] == "azure_speech, edge_tts"
    assert metadata["failure_service"] == "Narração TTS"


def test_moneyprinter_cli_args_marks_voice_for_azure_speech_sdk_v2():
    args = pipeline_worker._moneyprinter_cli_args(
        {
            "topic": "Tema",
            "voice": "en-US-BrianMultilingualNeural-Male",
            "generation_settings": {
                "voiceover_service": "Azure Speech SDK V2",
                "voiceover_mode": "Auto",
            },
        },
        "pexels",
    )
    assert args[args.index("--voice-name") + 1] == "en-US-BrianMultilingualNeural-V2-Male"


def test_video_helper_rejects_missing_azure_speech_sdk_v2_credentials(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "cli.py").write_text("# fake", encoding="utf-8")
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    storage.write_json("settings.json", {"moneyprinter_path": str(root), "pexels_api_keys": ["pexels-test-key"]})
    storage.write_json("tasks.json", [{"id": "video-no-azure", "state": "doing", "stage": "video", "topic": "Tema"}])
    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("não deve iniciar MPT sem credenciais Azure"))

    with pytest.raises(pipeline_worker.PipelineError, match="Azure Speech API") as raised:
        pipeline_worker._run_video_helper({
            "id": "video-no-azure",
            "topic": "Tema",
            "material_source": "pexels",
            "generation_settings": {
                "voiceover_service": "Azure Speech SDK V2",
                "voiceover_mode": "Auto",
                "voice": "en-US-BrianMultilingualNeural-Male",
            },
        })

    assert raised.value.failure_metadata["failure_config_fields"] == "azure_speech_key, azure_speech_region"


def test_video_helper_rejects_missing_selected_stock_key_with_actionable_message(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    with pytest.raises(pipeline_worker.PipelineError, match="API key de Pixabay"):
        pipeline_worker._run_video_helper({"id": "video-no-pixabay-key", "topic": "Tema", "material_source": "pixabay"})


def test_moneyprinter_cli_args_prioritise_wide_and_shorts_format_aspect_ratio():
    wide_args = pipeline_worker._moneyprinter_cli_args({"format": "wide", "generation_settings": {"video_aspect_ratio": "Portrait 9:16"}}, "pexels")
    shorts_args = pipeline_worker._moneyprinter_cli_args({"format": "shorts", "generation_settings": {"video_aspect_ratio": "Landscape 16:9"}}, "pexels")

    assert wide_args[wide_args.index("--video-aspect") + 1] == "16:9"
    assert shorts_args[shorts_args.index("--video-aspect") + 1] == "9:16"


def test_moneyprinter_cli_args_forwards_channel_subtitle_defaults():
    args = pipeline_worker._moneyprinter_cli_args(
        {"generation_settings": {
            "enable_subtitles": True,
            "subtitle_position": "Top",
            "subtitle_font": "Arial.ttf",
        }},
        "pexels",
    )

    assert "--subtitle-enabled" in args
    assert args[args.index("--subtitle-position") + 1] == "top"
    assert args[args.index("--font-name") + 1] == "Arial.ttf"


def test_normalise_video_route_keeps_stock_ai_and_music_separate():
    assert pipeline_worker._normalise_video_route({"style_wide": "Pexels/Pixabay"}, {}) == "pexels"
    assert pipeline_worker._normalise_video_route({"style_wide": "pixabay"}, {}) == "pixabay"
    assert pipeline_worker._normalise_video_route({"style_wide": "pexels", "material_source": "pixabay"}, {}) == "pixabay"
    assert pipeline_worker._normalise_video_route({"style_wide": "full_ia"}, {}) == "full_ia"
    assert pipeline_worker._normalise_video_route({"style_wide": "music", "music_mode": True}, {}) == "music"


def test_run_task_uses_only_full_ia_video_pool_for_full_ia_route(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    script_path = tmp_path / "prepared-script.md"
    script_path.write_text("Roteiro preparado para Full IA.", encoding="utf-8")
    video_path = tmp_path / "full-ia.mp4"
    video_path.write_bytes(b"mp4")
    thumbnail_path = tmp_path / "thumbnail.png"
    thumbnail_path.write_bytes(b"png")
    channel = {"id": "channel-full-ia", "name": "Canal Full IA", "language": "pt-BR", "niche": "tecnologia"}
    task = {
        "id": "video-full-ia",
        "state": "to_do",
        "stage": "script",
        "progress": 0,
        "topic": "Tema Full IA",
        "topic_source": "manual",
        "title": "Título Full IA",
        "tags": ["tecnologia"],
        "style_wide": "full_ia",
        "channel_id": channel["id"],
        "language": "pt-BR",
        "artifacts": {"script": str(script_path)},
        "generation_settings": {},
    }
    storage.write_json("channels.json", [channel])
    storage.write_json("tasks.json", [task])
    captured = {}
    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "_run_video_helper", lambda value: pytest.fail("Full IA não deve chamar o helper stock"))
    def fake_full_ia_pool(settings, prompt, **kwargs):
        captured["allowed_providers"] = kwargs["allowed_providers"]
        return video_path

    monkeypatch.setattr(pipeline_worker, "generate_video_from_pool", fake_full_ia_pool)
    monkeypatch.setattr(pipeline_worker, "generate_thumbnail_prompt", lambda *args, **kwargs: {"image_prompt": "thumbnail", "overlay_text": "FULL IA"})
    monkeypatch.setattr(pipeline_worker, "_generate_pipeline_thumbnail", lambda *args, **kwargs: thumbnail_path)
    monkeypatch.setattr(pipeline_worker, "upload_with_default_route", lambda *args, **kwargs: SimpleNamespace(ok=True, data={"uploaded": True}, message="ok"))

    result = pipeline_worker._run_task(task)

    assert result["state"] == "done"
    assert captured["allowed_providers"] == set(pipeline_worker.FULL_IA_VIDEO_PROVIDER_CODES)
    assert storage.read_json("tasks.json")[0]["artifacts"]["video"] == str(video_path)


def test_run_task_marks_music_only_ready_without_video_pipeline(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    music_path = tmp_path / "music.mp3"
    music_path.write_bytes(b"audio")
    channel = {"id": "channel-music", "name": "Canal Música", "language": "pt-BR"}
    task = {
        "id": "music-only",
        "state": "to_do",
        "stage": "script",
        "progress": 0,
        "topic": "",
        "style_wide": "music",
        "music_mode": True,
        "music_path": str(music_path),
        "channel_id": channel["id"],
        "artifacts": {},
        "generation_settings": {},
    }
    storage.write_json("channels.json", [channel])
    storage.write_json("tasks.json", [task])
    monkeypatch.setattr(pipeline_worker, "generate_topic_for_channel", lambda *args, **kwargs: pytest.fail("Apenas Música não deve gerar tema"))
    monkeypatch.setattr(pipeline_worker, "generate_script_document", lambda *args, **kwargs: pytest.fail("Apenas Música não deve gerar roteiro"))
    monkeypatch.setattr(pipeline_worker, "_run_video_helper", lambda value: pytest.fail("Apenas Música não deve gerar vídeo"))

    result = pipeline_worker._run_task(task)

    assert result["state"] == "done"
    assert result["music_ready"] is True
    assert result["video_ready"] is False
    assert result["artifacts"]["music"] == str(music_path)


def test_video_helper_passes_uploaded_voiceover_to_moneyprinterturbo(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    root = tmp_path / "MoneyPrinterTurbo"
    root.mkdir()
    (root / "cli.py").write_text("# fake", encoding="utf-8")
    (root / "config.toml").write_text("[app]\n", encoding="utf-8")
    voiceover = tmp_path / "narracao.wav"
    voiceover.write_bytes(b"audio")
    video_path = tmp_path / "generated.mp4"
    video_path.write_bytes(b"mp4")
    storage.write_json("settings.json", {"moneyprinter_path": str(root), "pexels_api_keys": ["pexels-test-key"]})
    storage.write_json("tasks.json", [{"id": "video_voiceover", "state": "doing", "stage": "video", "progress": 68, "topic": "Tema"}])
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return _FakePopen([f"VIDEO_FILE={video_path}\n"])

    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", fake_popen)
    result = pipeline_worker._run_video_helper(
        {
            "id": "video_voiceover",
            "topic": "Tema",
            "generation_settings": {"voiceover_mode": "Upload", "voiceover_file": str(voiceover)},
        }
    )

    assert result == video_path
    assert captured["command"][captured["command"].index("--custom-audio-file") + 1] == str(voiceover.resolve())


def test_video_helper_rejects_upload_mode_without_audio_file(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("settings.json", {"pexels_api_keys": ["pexels-test-key"]})
    with pytest.raises(pipeline_worker.PipelineError, match="ficheiro de narração válido"):
        pipeline_worker._run_video_helper(
            {
                "id": "video_missing_voiceover",
                "topic": "Tema",
                "generation_settings": {"voiceover_mode": "Upload", "voiceover_file": ""},
            }
        )


def test_video_helper_timeout_kills_subprocess_and_returns_pipeline_error(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("settings.json", {"pexels_api_keys": ["pexels-test-key"]})
    storage.write_json("tasks.json", [{"id": "video_timeout", "state": "doing", "stage": "video", "progress": 68, "topic": "Tema"}])
    process = _FakePopen([], stays_alive=True)
    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(pipeline_worker, "VIDEO_TIMEOUT_SECONDS", 0)

    with pytest.raises(pipeline_worker.PipelineError, match="excedeu o limite"):
        pipeline_worker._run_video_helper({"id": "video_timeout", "topic": "Tema"})

    assert process.returncode == -9


def test_video_helper_idle_timeout_kills_process_with_no_activity(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("settings.json", {"pexels_api_keys": ["pexels-test-key"]})
    storage.write_json("tasks.json", [{"id": "video_idle", "state": "doing", "stage": "video", "progress": 68, "topic": "Tema"}])
    process = _FakePopen([], stays_alive=True)
    monkeypatch.setattr(pipeline_worker.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(pipeline_worker, "VIDEO_TIMEOUT_SECONDS", 999)
    monkeypatch.setattr(pipeline_worker, "VIDEO_IDLE_TIMEOUT_SECONDS", 0)

    with pytest.raises(pipeline_worker.PipelineError, match="não apresentou actividade comprovada"):
        pipeline_worker._run_video_helper({"id": "video_idle", "topic": "Tema"})

    assert process.returncode == -9


def test_helper_log_activity_advances_only_when_file_mtime_changes(tmp_path):
    log_path = tmp_path / "moneyprinter.log"
    log_path.write_text("started", encoding="utf-8")
    first_mtime, advanced = pipeline_worker._latest_helper_log_activity(log_path, 0.0)

    unchanged_mtime, unchanged = pipeline_worker._latest_helper_log_activity(log_path, first_mtime)

    assert advanced is True
    assert first_mtime > 0
    assert unchanged is False
    assert unchanged_mtime == first_mtime


def test_long_stock_video_receives_bounded_extended_timeout(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    task = {
        "style_wide": "pexels",
        "video_script": "word " * 300,
    }

    assert pipeline_worker._video_timeout_seconds(task, {}) == pipeline_worker.LONG_STOCK_VIDEO_TIMEOUT_SECONDS
    assert pipeline_worker._task_stale_timeout_seconds({**task, "stage": "video"}) == pipeline_worker.LONG_STOCK_VIDEO_TIMEOUT_SECONDS + 5 * 60


def test_long_stock_video_uses_fewer_downloads_without_overriding_explicit_clip_duration(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    long_task = {"style_wide": "pexels", "video_script": "word " * 300}

    automatic_args = pipeline_worker._moneyprinter_cli_args(long_task, "pexels", settings={})
    explicit_args = pipeline_worker._moneyprinter_cli_args(
        {**long_task, "generation_settings": {"maximum_clip_duration": 7}},
        "pexels",
        settings={},
    )

    assert automatic_args[automatic_args.index("--video-clip-duration") + 1] == "15"
    assert explicit_args[explicit_args.index("--video-clip-duration") + 1] == "7"


def test_short_or_non_stock_video_keeps_default_timeout(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)

    assert pipeline_worker._video_timeout_seconds({"style_wide": "pexels", "video_script": "short"}, {}) == pipeline_worker.VIDEO_TIMEOUT_SECONDS
    assert pipeline_worker._video_timeout_seconds({"style_wide": "full_ia", "video_script": "word " * 300}, {}) == pipeline_worker.VIDEO_TIMEOUT_SECONDS


def test_stock_video_allows_slow_provider_activity_without_false_idle_failure(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)

    assert pipeline_worker._video_idle_timeout_seconds({"style_wide": "pexels"}, {}) == pipeline_worker.STOCK_VIDEO_IDLE_TIMEOUT_SECONDS
    assert pipeline_worker._video_idle_timeout_seconds({"style_wide": "pixabay"}, {}) == pipeline_worker.STOCK_VIDEO_IDLE_TIMEOUT_SECONDS
    assert pipeline_worker._video_idle_timeout_seconds({"style_wide": "full_ia"}, {}) == pipeline_worker.VIDEO_IDLE_TIMEOUT_SECONDS


def test_run_once_preserves_blocked_state_when_pipeline_is_stopped(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [{"id": "video_stopped", "state": "to_do", "stage": "video", "progress": 68, "topic": "Tema"}])
    monkeypatch.setattr(pipeline_worker, "_run_task", lambda task: (_ for _ in ()).throw(pipeline_worker.PipelineStopped("A tarefa foi parada pelo utilizador.")))

    result = pipeline_worker.run_once()

    assert result["ok"] is True
    assert result["status"] == "stopped"
    assert storage.read_json("tasks.json")[0]["state"] == "blocked"
    assert storage.read_json(pipeline_worker.PIPELINE_LOG_FILENAME)["status"] == "stopped"


def test_thumbnail_failure_keeps_video_artifact_ready_after_video_stage(tmp_path, monkeypatch):
    _isolate_storage(tmp_path, monkeypatch)
    video_path = tmp_path / "video-pronto.mp4"
    video_path.write_bytes(b"mp4")
    channel = {"id": "channel-1", "name": "Canal teste", "language": "pt-BR", "niche": "Teste"}
    task = {
        "id": "video_thumbnail_quota",
        "state": "to_do",
        "stage": "script",
        "progress": 0,
        "topic": "Tema com quota esgotada",
        "topic_source": "manual",
        "title": "Título pronto",
        "thumbnail_variant": {},
        "thumbnail_variants": [],
        "generation_settings": {"video_script": "Roteiro pronto", "video_keywords": "video, teste"},
        "channel_id": "channel-1",
        "language": "pt-BR",
        "artifacts": {},
    }
    storage.write_json("channels.json", [channel])
    storage.write_json("tasks.json", [task])

    monkeypatch.setattr(pipeline_worker, "_settings", lambda: {"youtube_batch_accounts": []})
    monkeypatch.setattr(pipeline_worker, "_channel_for_task", lambda value: channel)
    monkeypatch.setattr(pipeline_worker, "_blueprint_for_channel", lambda value: {})
    monkeypatch.setattr(pipeline_worker, "save_script_document", lambda script: {"path": "script.md"})
    monkeypatch.setattr(pipeline_worker, "_run_video_helper", lambda value: video_path)
    monkeypatch.setattr(pipeline_worker, "generate_thumbnail_prompt", lambda *args, **kwargs: {"image_prompt": "prompt depois do vídeo", "overlay_text": "THUMB DEPOIS"})
    monkeypatch.setattr(
        pipeline_worker,
        "_generate_pipeline_thumbnail",
        lambda *args, **kwargs: (_ for _ in ()).throw(ThumbnailGenerationError("HTTP 429 quota")),
    )
    monkeypatch.setattr(pipeline_worker, "upload_with_default_route", lambda *args, **kwargs: pytest.fail("upload não deve ocorrer sem thumbnail"))

    result = pipeline_worker.run_once()

    assert result["ok"] is False
    persisted = storage.read_json("tasks.json")[0]
    assert persisted["state"] == "failed"
    assert persisted["stage"] == "thumbnail"
    assert persisted["progress"] == 86
    assert persisted["video_ready"] is True
    assert persisted["artifacts"]["video"] == str(video_path)
    assert "vídeo já está disponível" in persisted["error"]
    assert result["task_id"] == task["id"]


def test_pipeline_stage_order_places_video_before_thumbnail_prompt():
    from hermes_ui.domain import STAGES

    assert STAGES.index("video") < STAGES.index("thumbnail_prompt") < STAGES.index("thumbnail") < STAGES.index("upload")


def test_azure_v2_long_audio_error_is_attributed_to_specific_api():
    metadata = pipeline_worker._failure_attribution(
        {"style_wide": "pexels"},
        {},
        "video",
        error=(
            "re v2 speech synthesis error: Connection was closed by the remote host. "
            "Error code: 1007. Error details: The processed audio has exceeded "
            "the configured maximum media duration of 600000ms"
        ),
    )
    assert metadata["failure_api"] == "Azure Speech SDK V2 API"
    assert metadata["failure_provider"] == "azure_speech"
    assert metadata["failure_service"] == "Narração TTS — limite de 600000 ms"


def test_terminal_helper_detail_ignores_configuration_prefix():
    detail = pipeline_worker._terminal_helper_detail(
        "\n".join(
            [
                "[MoneyPrinterTurbo] using existing project: C:\\Users\\danha\\AppData\\Local\\THUNDERBOLT\\MoneyPrinterTurbo",
                "[MoneyPrinterTurbo] updated configuration fields: llm_provider, openai_api_key, openai_base_url",
                "[MoneyPrinterTurbo] synthesizing Azure Speech V2 in safe chunks before MoneyPrinterTurbo",
                "AZURE_CHUNK_PROGRESS=1/3",
                "MPT_ERROR=Azure Speech SDK V2 falhou no segmento 2/3",
            ]
        )
    )
    assert "MPT_ERROR=Azure Speech SDK V2 falhou no segmento 2/3" in detail
    assert "updated configuration fields" not in detail
    assert "using existing project" not in detail


def test_moneyprinter_cli_args_marks_default_voice_for_azure_v2_when_voice_is_empty():
    args = pipeline_worker._moneyprinter_cli_args(
        {
            "topic": "Tema",
            "generation_settings": {
                "voiceover_service": "Azure Speech SDK V2",
                "voiceover_mode": "Auto",
            },
        },
        "pexels",
    )
    voice = args[args.index("--voice-name") + 1]
    assert voice.casefold().startswith("en-us-jennyneural-v2")


def test_azure_v2_chunking_failure_is_attributed_to_azure_v2_api():
    metadata = pipeline_worker._failure_attribution(
        {"style_wide": "pexels"},
        {},
        "video",
        error="Azure Speech SDK V2 falhou na síntese segmentada no segmento 2/4",
    )
    assert metadata["failure_api"] == "Azure Speech SDK V2 API"
    assert metadata["failure_provider"] == "azure_speech"
    assert metadata["failure_service"] == "Narração TTS — segmentação Azure"


def test_terminal_helper_detail_prioritises_mpt_error_over_startup_output():
    output = "\n".join(
        [
            "[MoneyPrinterTurbo] Pexels key validation completed: valid=1, rejected=0, unknown=0",
            "[MoneyPrinterTurbo] installing or verifying project dependencies with uv",
            "TASK_DIR=C:\\Users\\danha\\AppData\\Local\\THUNDERBOLT\\MoneyPrinterTurbo",
            "MPT_ERROR=video generation failed with exit code 1; log: C:\\Users\\danha\\...\\run.log",
        ]
    )
    detail = pipeline_worker._terminal_helper_detail(output)
    assert "MPT_ERROR=video generation failed" in detail
    assert "Pexels key validation" not in detail
    assert "installing or verifying project dependencies" not in detail
    assert "TASK_DIR=" not in detail
