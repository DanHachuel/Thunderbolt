from pathlib import Path

import hermes_ui.music_blueprints as music_blueprints


def test_seed_music_blueprints_is_idempotent(tmp_path, monkeypatch):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "style.md").write_text("# 1. Nome da Música\n", encoding="utf-8")
    destination = tmp_path / "storage"
    monkeypatch.setattr(music_blueprints, "SEED_MUSIC_BLUEPRINTS", seed)
    monkeypatch.setattr(music_blueprints, "MUSIC_BLUEPRINTS", destination)

    assert music_blueprints.seed_music_blueprints() == 1
    assert music_blueprints.seed_music_blueprints() == 0
    assert (destination / "style.md").read_text(encoding="utf-8").startswith("# 1.")


def test_save_music_blueprint_writes_reusable_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(music_blueprints, "MUSIC_BLUEPRINTS", tmp_path)

    saved = music_blueprints.save_music_blueprint("Fado / Noite", "# 1. Nome da Música\n# 4. Estilo / Style Prompt")

    assert saved == tmp_path / "Fado - Noite.md"
    assert saved.read_text(encoding="utf-8").endswith("\n")
    assert [path.name for path in music_blueprints.list_music_blueprint_documents()] == ["Fado - Noite.md"]


def test_save_music_blueprint_rejects_missing_required_values(tmp_path, monkeypatch):
    monkeypatch.setattr(music_blueprints, "MUSIC_BLUEPRINTS", tmp_path)
    for name, content in (("", "texto"), ("Nome", "")):
        try:
            music_blueprints.save_music_blueprint(name, content)
        except ValueError:
            pass
        else:
            raise AssertionError("Valores obrigatórios vazios deveriam falhar")
