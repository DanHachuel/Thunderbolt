import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _isolated_storage(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(storage_root))
    from hermes_ui import storage

    # monkeypatch.setattr restaura os globals no fim de cada teste; atribuição
    # directa vazava STORAGE/STATE para os testes seguintes da sessão.
    monkeypatch.setattr(storage, "STORAGE", storage_root)
    monkeypatch.setattr(storage, "STATE", storage_root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", storage_root / "blueprints")
    storage.ensure_storage()
    return storage


def test_concurrent_task_mutations_preserve_every_video(tmp_path, monkeypatch):
    storage = _isolated_storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [])

    def add_task(index):
        def mutate(tasks):
            tasks.append({"id": f"video-{index}", "state": "to_do"})

        storage.update_json("tasks.json", [], mutate)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(add_task, range(32)))

    tasks = storage.read_json("tasks.json")
    assert len(tasks) == 32
    assert {task["id"] for task in tasks} == {f"video-{index}" for index in range(32)}


def test_state_lock_unlink_tolerates_transient_permission_error(tmp_path, monkeypatch):
    """REAL-BUG #1 (fix 0.9.48): no Windows o unlink do lock pode receber um
    PermissionError transitório (antivírus a segurar o ficheiro); sem retry o
    lock vazava e todas as escritas seguintes falhavam com TimeoutError de
    30s enquanto o pid do dono estivesse vivo. O retry curto (3 tentativas,
    50ms) liberta o lock sem partir a escrita já concluída."""
    storage = _isolated_storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [])
    real_unlink = os.unlink
    failures = {"count": 0}

    def flaky_unlink(path, *args, **kwargs):
        if str(path).endswith(".tasks.json.lock") and failures["count"] < 2:
            failures["count"] += 1
            raise PermissionError(13, "O arquivo já está sendo usado por outro processo")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(storage.os, "unlink", flaky_unlink)

    def mutate(tasks):
        tasks.append({"id": "video-lock", "state": "to_do"})

    storage.update_json("tasks.json", [], mutate)

    # O retry absorveu os dois erros transitórios e a escrita foi concluída.
    assert failures["count"] == 2
    assert storage.read_json("tasks.json")[0]["id"] == "video-lock"
    # O lock foi realmente libertado: uma segunda escrita segue sem esperar
    # pelo stale-reclaim (que não remove locks de pids vivos).
    assert not (storage.STATE / ".tasks.json.lock").exists()
    storage.update_json("tasks.json", [], lambda tasks: tasks.append({"id": "video-second", "state": "to_do"}))
    assert len(storage.read_json("tasks.json")) == 2


def test_corrupt_protected_task_file_is_not_replaced_by_empty_list(tmp_path, monkeypatch):
    storage = _isolated_storage(tmp_path, monkeypatch)
    task_path = storage.STATE / "tasks.json"
    task_path.write_text("{ dados incompletos", encoding="utf-8")

    with pytest.raises(storage.StorageIntegrityError):
        storage.read_json("tasks.json", [])

    assert task_path.read_text(encoding="utf-8") == "{ dados incompletos"
    assert list(storage.STATE.glob("tasks.json.corrupt-*"))


def test_read_json_survives_windows_lock_permission_error(tmp_path, monkeypatch):
    storage = _isolated_storage(tmp_path, monkeypatch)
    storage.write_json("display_names.json", {"blueprints": {}, "prompt_masters": {"prompt.md": "Prompt"}})
    original_open = storage.os.open

    def permission_denied_for_lock(path, flags, *args):
        if str(path).endswith(".display_names.json.lock"):
            raise PermissionError(13, "Permission denied")
        return original_open(path, flags, *args)

    monkeypatch.setattr(storage.os, "open", permission_denied_for_lock)

    assert storage.read_json("display_names.json")["prompt_masters"]["prompt.md"] == "Prompt"


def test_read_json_cache_returns_copies_and_invalidates_after_write(tmp_path, monkeypatch):
    storage = _isolated_storage(tmp_path, monkeypatch)
    storage.write_json("tasks.json", [{"id": "one"}])

    first = storage.read_json("tasks.json")
    first[0]["id"] = "mutated-only-in-memory"
    assert storage.read_json("tasks.json")[0]["id"] == "one"

    storage.write_json("tasks.json", [{"id": "two"}])
    assert storage.read_json("tasks.json")[0]["id"] == "two"


def test_atomic_write_retries_transient_replace_permission_error(tmp_path, monkeypatch):
    storage = _isolated_storage(tmp_path, monkeypatch)
    path = storage.STATE / "tasks.json"
    original_replace = storage.os.replace
    attempts = 0

    def flaky_replace(source, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(13, "Permission denied")
        original_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", flaky_replace)

    storage.atomic_write(path, [{"id": "video-1", "progress": 80}])

    assert attempts == 3
    assert storage.read_json("tasks.json")[0]["progress"] == 80


def test_install_merges_legacy_tasks_when_new_storage_already_exists(tmp_path):
    legacy_state = tmp_path / "Hermes-UI" / "storage" / "state"
    # No Windows o install.mjs usa LOCALAPPDATA/THUNDERBOLT como home por omissão
    # (não .thunderbolt); THUNDERBOLT_HOME NÃO pode ser definido porque desativa
    # a migração (migrateLegacyInstallation retorna cedo). Isolar LOCALAPPDATA
    # mantém o teste hermético em ambas as plataformas.
    if sys.platform == "win32":
        current_state = tmp_path / "AppData" / "Local" / "THUNDERBOLT" / "storage" / "state"
    else:
        current_state = tmp_path / ".thunderbolt" / "storage" / "state"
    legacy_state.mkdir(parents=True)
    current_state.mkdir(parents=True)
    (legacy_state / "tasks.json").write_text(
        json.dumps([{"id": "legacy-video", "state": "to_do", "topic": "Vídeo antigo"}]),
        encoding="utf-8",
    )
    (legacy_state / "queues.json").write_text(json.dumps({"script": ["legacy-video"]}), encoding="utf-8")
    (current_state / "tasks.json").write_text("[]\n", encoding="utf-8")
    (current_state / "queues.json").write_text(json.dumps({"script": []}), encoding="utf-8")

    environment = os.environ.copy()
    # HOME cobre sistemas POSIX; USERPROFILE/LOCALAPPDATA cobrem as resoluções
    # do install.mjs no Windows (getUserHome e o home por omissão).
    # THUNDERBOLT_HOME é removido propositadamente: um valor explícito desativa
    # a migração legada (migrateLegacyInstallation).
    environment["HOME"] = str(tmp_path)
    environment["USERPROFILE"] = str(tmp_path)
    environment["LOCALAPPDATA"] = str(tmp_path / "AppData" / "Local")
    environment.pop("THUNDERBOLT_HOME", None)
    completed = subprocess.run(
        ["node", str(ROOT / "scripts" / "install.mjs"), "--skip-python-deps", "--skip-moneyprinter"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        # install.mjs escreve UTF-8; sem isto o Windows decodifica com cp1252
        # e as asserções de mensagens em português falham por mojibake.
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    tasks = json.loads((current_state / "tasks.json").read_text(encoding="utf-8"))
    queues = json.loads((current_state / "queues.json").read_text(encoding="utf-8"))
    assert [task["id"] for task in tasks] == ["legacy-video"]
    assert queues["script"] == ["legacy-video"]
    assert "não elimina tarefas" in completed.stdout
