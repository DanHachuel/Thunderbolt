import os
import time

from hermes_ui.storage import _ensure_directory, _state_lock


def test_ensure_directory_is_idempotent(tmp_path):
    path = tmp_path / "blueprints" / "importados"
    _ensure_directory(path)
    _ensure_directory(path)
    assert path.is_dir()


def test_ensure_directory_replaces_conflicting_file(tmp_path):
    path = tmp_path / "blueprints" / "nichos"
    path.parent.mkdir(parents=True)
    path.write_text("stale file", encoding="utf-8")
    _ensure_directory(path)
    assert path.is_dir()


def test_read_only_state_lock_does_not_wait_for_existing_writer(tmp_path):
    path = tmp_path / "channels.json"
    lock_path = tmp_path / ".channels.json.lock"
    lock_path.write_text("pid=999999\n", encoding="ascii")

    with _state_lock(path, read_only=True):
        assert lock_path.exists()


def test_write_lock_reclaims_dead_process_lock(tmp_path):
    path = tmp_path / "channels.json"
    lock_path = tmp_path / ".channels.json.lock"
    lock_path.write_text("pid=999999\n", encoding="ascii")
    old_time = time.time() - 5
    os.utime(lock_path, (old_time, old_time))

    with _state_lock(path):
        assert lock_path.exists()
        assert lock_path.read_text(encoding="ascii").startswith(f"pid={os.getpid()}")

    assert not lock_path.exists()
