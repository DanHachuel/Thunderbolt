from hermes_ui import mcp_server, storage


def test_lista_txt_control_file_is_not_exposed_in_blueprint_catalogs(tmp_path, monkeypatch):
    blueprints = tmp_path / "blueprints"
    imported = blueprints / "importados"
    imported.mkdir(parents=True)
    (imported / "LISTA.txt").write_text("internal control", encoding="utf-8")
    (imported / "LISTA.txt.json").write_text('{"name": "internal control"}', encoding="utf-8")
    (imported / "FINANCE USA.json").write_text('{"name": "FINANCE USA"}', encoding="utf-8")

    monkeypatch.setattr(storage, "BLUEPRINTS", blueprints)
    monkeypatch.setattr(storage, "ensure_storage", lambda: None)

    assert [path.name for path in storage.list_blueprint_files()] == ["FINANCE USA.json"]
    assert [item["filename"] for item in mcp_server._list_blueprints()] == ["FINANCE USA.json"]


def test_control_files_other_tabs_and_demo_never_enter_the_blueprint_catalog(tmp_path, monkeypatch):
    """0.9.74: o catálogo mostrava o registo de pares, o demo 'Canal Hermes
    Demo' e ficheiros das pastas de thumbnails/brandings como Blueprints."""
    blueprints = tmp_path / "blueprints"
    for folder in ("importados", "thumbnails", "brandings", "music", "conteudo", "canais"):
        (blueprints / folder).mkdir(parents=True)
    (blueprints / "thumbnail_blueprint_pairs.json").write_text("{}", encoding="utf-8")
    (blueprints / "importados" / "thumbnail_blueprint_pairs.json").write_text("{}", encoding="utf-8")
    (blueprints / "importados" / "demo-content-hermes.json").write_text('{"id": "demo-content-hermes"}', encoding="utf-8")
    (blueprints / "importados" / "FINANCE USA.json").write_text('{"name": "FINANCE USA"}', encoding="utf-8")
    (blueprints / "canais" / "MeuCanal.json").write_text('{"name": "Meu Canal"}', encoding="utf-8")
    (blueprints / "thumbnails" / "FINANCE_Thumbnail_Blueprint.md").write_text("thumb", encoding="utf-8")
    (blueprints / "thumbnails" / "pares.json").write_text("{}", encoding="utf-8")
    (blueprints / "brandings" / "Branding.json").write_text("{}", encoding="utf-8")
    (blueprints / "conteudo" / "Duplicado.json").write_text("{}", encoding="utf-8")
    (blueprints / "music" / "Estilo.md").write_text("musica", encoding="utf-8")
    (blueprints / "FINANCE USA.md").write_text("conteudo", encoding="utf-8")
    (blueprints / "FINANCE USA_Thumbnail_Blueprint.md").write_text("thumb", encoding="utf-8")

    monkeypatch.setattr(storage, "BLUEPRINTS", blueprints)
    monkeypatch.setattr(storage, "CONTENT_BLUEPRINTS", blueprints)
    monkeypatch.setattr(storage, "ensure_storage", lambda: None)

    listed = sorted(path.name for path in storage.list_blueprint_files())
    assert listed == ["FINANCE USA.json", "MeuCanal.json"]
    assert sorted(item["filename"] for item in mcp_server._list_blueprints()) == ["FINANCE USA.json", "MeuCanal.json"]

    # Os Blueprints de conteúdo (.md da raiz) ficam na lista única, mas os
    # ficheiros com nome de Thumbnail Blueprint pertencem só à aba Thumbnails.
    content = [path.name for path in storage.list_content_blueprint_files()]
    assert content == ["FINANCE USA.md"]


def test_blueprints_tab_has_no_folder_selector_or_content_separator():
    """0.9.74: sem seletor de pastas e sem separador 'Blueprints de conteúdo'."""
    from pathlib import Path

    main_source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    render_block = main_source.split("def render_blueprints():", 1)[1].split("def render_music_blueprints():", 1)[0]
    assert 'selectbox("Pasta"' not in render_block
    assert "Blueprints de conteúdo" not in render_block
    assert "content_blueprint_search" not in render_block
    # importações vão directamente para a raiz da biblioteca
    assert "destination = BLUEPRINTS / safe_name" in render_block
    # uma única lista com a contagem total
    assert 'st.subheader(f"Blueprints ({total})")' in render_block
