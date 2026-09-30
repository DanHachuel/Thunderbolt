from hermes_ui import storage


def test_finance_content_seeds_are_separate_from_thumbnail_seed():
    from pathlib import Path

    content = sorted(Path("seed/blueprints/conteudo").glob("FINANCE*.md"))
    thumbnails = sorted(Path("seed/blueprints/thumbnails").glob("FINANCE*.md"))

    assert len(content) == 15
    assert [path.name for path in thumbnails] == ["FINANCE_Thumbnail_Blueprint.md"]


def test_seed_blueprints_migrates_legacy_finance_markdown(tmp_path, monkeypatch):
    seed_root = tmp_path / "seed"
    (seed_root / "thumbnails").mkdir(parents=True)
    (seed_root / "conteudo").mkdir(parents=True)
    (seed_root / "thumbnails" / "FINANCE_Thumbnail_Blueprint.md").write_text("thumbnail", encoding="utf-8")
    (seed_root / "conteudo" / "FINANCE BRAZIL.md").write_text("content", encoding="utf-8")
    blueprints = tmp_path / "storage" / "blueprints"
    thumbnail_destination = blueprints / "thumbnails"
    thumbnail_destination.mkdir(parents=True)
    (thumbnail_destination / "FINANCE BRAZIL.md").write_text("legacy content", encoding="utf-8")

    monkeypatch.setattr(storage, "SEED_BLUEPRINTS", seed_root)
    monkeypatch.setattr(storage, "SEED_THUMBNAIL_BLUEPRINTS", seed_root / "thumbnails")
    monkeypatch.setattr(storage, "SEED_CONTENT_BLUEPRINTS", seed_root / "conteudo")
    monkeypatch.setattr(storage, "BLUEPRINTS", blueprints)
    monkeypatch.setattr(storage, "CONTENT_BLUEPRINTS", blueprints / "conteudo")

    storage.seed_blueprints()

    assert (blueprints / "conteudo" / "FINANCE BRAZIL.md").read_text(encoding="utf-8") == "legacy content"
    assert not (thumbnail_destination / "FINANCE BRAZIL.md").exists()
    assert (thumbnail_destination / "FINANCE_Thumbnail_Blueprint.md").exists()
