from __future__ import annotations

import json
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_social_auto_upload_storage_is_ignored_by_npm_pack_dry_run():
    private_dir = ROOT / "storage" / "state" / "social_auto_upload"
    created_dirs: list[Path] = []
    current = private_dir
    while not current.exists():
        created_dirs.append(current)
        current = current.parent
    private_dir.mkdir(parents=True, exist_ok=True)
    sentinel = private_dir / f"npm-pack-sentinel-{uuid.uuid4().hex}.json"
    sentinel.write_text('{"private":"session"}\n', encoding="utf-8")
    try:
        completed = subprocess.run(
            ["npm", "pack", "--dry-run", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
        payload = json.loads(completed.stdout)
        files = [str(item.get("path") or "").replace("\\", "/") for item in payload[0].get("files", [])]
        assert "app/social_auto_upload_ui.py" in files
        assert not any(path == "storage" or path.startswith("storage/") for path in files)
        assert not any(sentinel.name in path for path in files)
    finally:
        sentinel.unlink(missing_ok=True)
        for directory in created_dirs:
            try:
                directory.rmdir()
            except OSError:
                break
