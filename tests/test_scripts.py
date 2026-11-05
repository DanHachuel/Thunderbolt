import json
from pathlib import Path

import pytest

from hermes_ui.creative_generation import CreativeGenerationError
from hermes_ui import pipeline_worker, script_documents, script_generation


def _settings():
    return {
        "llm_provider": "openai",
        "openai_api_key": "test-key",
        "openai_base_url": "https://llm.example/v1",
        "openai_model_name": "test-model",
    }


def test_generate_video_script_includes_blueprint_context(monkeypatch):
    captured = {}

    def fake_chat(settings, system, user):
        captured["settings"] = settings
        captured["system"] = system
        captured["user"] = json.loads(user)
        # 1.0.61 - o canal sem tempo explicito assume 20:00 (3.000 palavras); o
        # roteiro faux tem de cumprir o alvo para passar na validacao rigida.
        return {"title": "As muralhas esquecidas", "summary": "Um roteiro documental", "content": "# Gancho\n\n## Cena 1\n\n" + "A cidade antiga esconde um misterio por baixo da poeira. " * 500}

    monkeypatch.setattr(script_generation, "_chat_json", fake_chat)
    result = script_generation.generate_script_document(
        _settings(),
        document_type="Roteiro de vídeo",
        title="As muralhas esquecidas",
        brief="Explicar o mistério de uma cidade antiga.",
        language="01 – Inglês",
        channel={"id": "channel-1", "name": "History Vault", "default_blueprint_id": "bp-history"},
        blueprint={"id": "bp-history", "name": "História", "target_niche": "civilizações antigas"},
        structure_notes="5 cenas, tom documental",
        generation_settings={"video_format": "shorts", "enable_subtitles": True, "voice": "en-US-AriaNeural-Female"},
    )

    assert result["document_type"] == "video_script"
    assert result["blueprint_name"] == "História"
    assert result["content"].startswith("# Gancho")
    assert captured["user"]["blueprint"]["target_niche"] == "civilizações antigas"
    assert captured["user"]["structure_notes"] == "5 cenas, tom documental"
    assert captured["user"]["generation_settings"]["video_format"] == "shorts"
    assert result["generation_settings"]["enable_subtitles"] is True


def test_generate_music_lyrics_requires_brief():
    with pytest.raises(CreativeGenerationError, match="briefing"):
        script_generation.generate_script_document(
            _settings(),
            document_type="Letra de música",
            title="",
            brief="",
            language="36 – Português (Brasil)",
        )


def test_save_script_document_writes_markdown_and_history(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    history = []
    monkeypatch.setattr(script_documents, "STORAGE", storage_root)
    monkeypatch.setattr(script_documents, "ensure_storage", lambda: None)
    monkeypatch.setattr(script_documents, "read_json", lambda _name, _default=None: list(history))
    monkeypatch.setattr(script_documents, "write_json", lambda _name, value: history.__setitem__(slice(None), value))

    record = script_documents.save_script_document(
        {
            "document_type": "music_lyrics",
            "title": "Canção do Norte",
            "summary": "Uma viagem interior",
            "content": "[Verso]\nVento sobre o mar",
            "language": "36 – Português (Brasil)",
            "blueprint_id": "nature-vault",
            "blueprint_name": "Nature Vault",
            "channel_name": "Canal Musical",
        }
    )

    path = Path(record["path"])
    assert path.parent == storage_root / "scripts"
    assert path.is_file()
    markdown = path.read_text(encoding="utf-8")
    assert "Canção do Norte" in markdown
    assert "blueprint_id: nature-vault" in markdown
    assert "blueprint: Nature Vault" in markdown
    assert history[0]["filename"] == path.name
    assert script_documents.read_script_document(record).endswith("Vento sobre o mar\n")


def test_update_and_delete_script_document_preserve_index_and_file(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    history = []
    monkeypatch.setattr(script_documents, "STORAGE", storage_root)
    monkeypatch.setattr(script_documents, "ensure_storage", lambda: None)
    monkeypatch.setattr(script_documents, "read_json", lambda _name, _default=None: list(history))
    monkeypatch.setattr(script_documents, "write_json", lambda _name, value: history.__setitem__(slice(None), value))

    record = script_documents.save_script_document(
        {"title": "Roteiro antigo", "content": "# Corpo original", "channel_name": "Canal", "blueprint_id": "old-id", "blueprint_name": "Old"}
    )
    updated = script_documents.update_script_document_metadata(record["id"], {"blueprint_id": "new-id", "blueprint": "New"})
    assert updated["blueprint_id"] == "new-id"
    assert updated["blueprint_name"] == "New"
    assert "blueprint_id: new-id" in Path(record["path"]).read_text(encoding="utf-8")
    assert script_documents.update_script_document(record["id"], "---\nid: %s\n---\n\n# Corpo editado" % record["id"])["title"] == "Roteiro antigo"
    assert "# Corpo editado" in Path(record["path"]).read_text(encoding="utf-8")
    assert script_documents.delete_script_document(record["id"]) is True
    assert not Path(record["path"]).exists()
    assert history == []


def test_pipeline_resolves_blueprint_from_imported_file(monkeypatch, tmp_path):
    blueprint_path = tmp_path / "BlueprintNatureVault.json"
    blueprint_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(pipeline_worker, "list_blueprint_files", lambda: [blueprint_path])
    monkeypatch.setattr(pipeline_worker, "load_blueprint_file", lambda _path: {"name": "Nature Vault", "target_niche": "natureza"})
    monkeypatch.setattr(pipeline_worker, "get_display_name", lambda _kind, _path, fallback: fallback)

    resolved = pipeline_worker._blueprint_for_channel({"default_blueprint_id": "BlueprintNatureVault"})

    assert resolved["name"] == "Nature Vault"
    assert resolved["id"] == "BlueprintNatureVault"
    assert resolved["target_niche"] == "natureza"
