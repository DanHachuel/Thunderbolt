from __future__ import annotations

import pytest

from hermes_ui import domain, storage


def test_uncertain_upload_retry_requires_explicit_manual_confirmation(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", root / "tiktok" / "prompts_master")
    monkeypatch.setattr(storage, "MEDIA_DOWNLOADS", root / "media_downloads")
    monkeypatch.setattr(storage, "NICHES_DATA", root / "data" / "niches")
    storage.ensure_storage()
    storage.write_json("tasks.json", [{"id": "task1", "state": "blocked", "stop_reason": "upload_uncertain", "upload_uncertain": True}])

    with pytest.raises(ValueError, match="Verifique manualmente"):
        domain.retry_task_with_current_settings("task1")

    updated = domain.retry_task_with_current_settings("task1", confirm_upload_uncertain=True)
    assert updated["state"] == "to_do"
    assert updated["upload_uncertainty_user_confirmed"] is True
    assert "stop_reason" not in updated
