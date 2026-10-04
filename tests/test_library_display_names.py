import json
from pathlib import Path

import pytest


def test_display_names_are_persisted_separately_from_library_files(tmp_path, monkeypatch):
    # Isolamento hermético: o env var THUNDERBOLT_STORAGE_DIR só é lido na
    # importação do módulo; em vez disso, apontar os globals para o tmp do teste
    # (monkeypatch restaura no fim) para não escrever no storage real do repo.
    from hermes_ui import storage

    monkeypatch.setattr(storage, "STORAGE", tmp_path / "storage")
    monkeypatch.setattr(storage, "STATE", tmp_path / "storage" / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", tmp_path / "storage" / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", tmp_path / "storage" / "tiktok" / "prompts_master")
    storage.ensure_storage()
    blueprint = storage.BLUEPRINTS / "importados" / "example.json"
    blueprint.write_text(json.dumps({"id": "bp-example", "name": "Original Blueprint"}), encoding="utf-8")
    prompt = storage.TIKTOK_PROMPT_MASTERS / "example.md"
    prompt.write_text("# Original Prompt\n", encoding="utf-8")

    storage.set_display_name("blueprints", blueprint, "Blueprint Renomeado")
    storage.set_display_name("prompt_masters", prompt, "Prompt Renomeado")

    assert storage.get_display_name("blueprints", blueprint, "fallback") == "Blueprint Renomeado"
    assert storage.get_display_name("prompt_masters", prompt, "fallback") == "Prompt Renomeado"
    assert blueprint.name == "example.json"
    assert prompt.name == "example.md"
    saved = json.loads((storage.STATE / "display_names.json").read_text(encoding="utf-8"))
    assert saved["blueprints"]["importados/example.json"] == "Blueprint Renomeado"
    assert saved["prompt_masters"]["example.md"] == "Prompt Renomeado"
