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
