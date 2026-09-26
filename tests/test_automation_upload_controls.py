from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")


def test_youtube_automation_has_upload_controls_with_safe_default():
    assert '"Upload automático"' in MAIN_SOURCE
    assert 'youtube_automation_auto_upload' in MAIN_SOURCE
    assert 'key=f"youtube_automation_auto_upload_{\'posted\' if posted_only else \'pipeline\'}"' in MAIN_SOURCE
    assert MAIN_SOURCE.count('key=f"youtube_automation_auto_upload_{\'posted\' if posted_only else \'pipeline\'}"') == 1
    assert 'value=bool(settings.get("youtube_automation_auto_upload", False))' in MAIN_SOURCE
    assert '"Upload ok"' in MAIN_SOURCE
    assert '"Upload"' in MAIN_SOURCE


def test_upload_button_requires_video_and_thumbnail():
    assert "def _upload_ready_for_task" in MAIN_SOURCE
    assert 'video_path is not None and thumbnail_path is not None' in MAIN_SOURCE
    assert "disabled=not upload_ready or upload_ok" in MAIN_SOURCE


def test_pipeline_reaches_100_before_optional_upload():
    assert 'stage="ready_upload", state="done", progress=100' in WORKER_SOURCE
    assert 'youtube_automation_auto_upload' in WORKER_SOURCE
    assert '_update(task_id, stage="upload", state="doing", progress=100' in WORKER_SOURCE
