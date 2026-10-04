from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
STORAGE_SOURCE = (ROOT / "hermes_ui" / "storage.py").read_text(encoding="utf-8")
PACKAGE_SOURCE = (ROOT / "package.json").read_text(encoding="utf-8")


def test_tiktok_pipeline_is_separate_and_expansible():
    # Desde a reorganização da navegação por caminhos, a área de Prompt Masters
    # do TikTok é um item de nível superior ("Prompt-Masters Tiktok") dentro de
    # blueprint_items, com caminho próprio, aliases dos nomes antigos
    # ("Prompts Master"/"Pipeline TikTok") e renderer dedicado — separada e
    # expansível como na estrutura anterior.
    assert 'blueprint_items = [' in MAIN_SOURCE
    assert '("Prompt-Masters Tiktok", ":material/auto_awesome:", "Prompt-Masters Tiktok"),' in MAIN_SOURCE
    assert '"Prompt-Masters Tiktok": "/blueprints/prompt-masters-tiktok"' in MAIN_SOURCE
    assert '"Prompts Master": "Prompt-Masters Tiktok",' in MAIN_SOURCE
    assert '"Prompt-Masters Tiktok": render_tiktok_prompt_masters,' in MAIN_SOURCE
    assert 'def render_tiktok_prompt_masters():' in MAIN_SOURCE


def test_prompt_master_storage_is_not_blueprints_storage():
    assert 'TIKTOK_PROMPT_MASTERS = STORAGE / "tiktok" / "prompts_master"' in STORAGE_SOURCE
    assert 'def list_prompt_master_files()' in STORAGE_SOURCE
    assert 'def load_prompt_master_file(path: Path)' in STORAGE_SOURCE
    assert 'seed/prompt_masters/**/*.md' in PACKAGE_SOURCE
    assert 'storage/tiktok/prompts_master/**/*.md' not in PACKAGE_SOURCE
    assert 'BLUEPRINTS / "importados"' in STORAGE_SOURCE
    # O default de display_names ganhou as secções music e music_lyrics.
    assert '"display_names.json": {"blueprints": {}, "prompt_masters": {}, "music": {}, "music_lyrics": {}}' in STORAGE_SOURCE
    assert 'def get_display_name(kind: str, path: Path, fallback: str)' in STORAGE_SOURCE
    assert 'def set_display_name(kind: str, path: Path, name: str)' in STORAGE_SOURCE


def test_prompt_master_ui_has_upload_library_editor_and_actions():
    for label in (
        "Subir Prompt Master (.md)",
        "Guardar Prompt Master",
        "Prompts Master existentes",
        "Pesquisar Prompt Master",
        "Guardar alterações",
        "Descarregar",
        "Apagar",
    ):
        assert label in MAIN_SOURCE
    assert 'mime="text/markdown"' in MAIN_SOURCE
    assert 'st.markdown(content)' in MAIN_SOURCE
    assert 'def _render_card_pencil(edit_key: str)' in MAIN_SOURCE
    assert 'help="Editar nome de apresentação"' in MAIN_SOURCE
    assert '_render_card_pencil(f"rename_blueprints_' in MAIN_SOURCE
    assert '_render_card_pencil(f"rename_prompt_masters_' in MAIN_SOURCE
    assert '_render_library_name_editor("blueprints", path, title)' in MAIN_SOURCE
    assert '_render_library_name_editor("prompt_masters", path, heading)' in MAIN_SOURCE


def test_library_cards_show_only_display_names_without_paths_or_extensions():
    assert 'with st.expander(title):' in MAIN_SOURCE
    assert 'with st.expander(heading, expanded=False):' in MAIN_SOURCE
    assert 'st.caption(f"Ficheiro: {path}")' not in MAIN_SOURCE
    assert 'st.caption(f"Ficheiro TikTok: `{path}`")' not in MAIN_SOURCE
    assert 'with st.expander(f"{title} — {path.relative_to(BLUEPRINTS)}")' not in MAIN_SOURCE
    assert 'with st.expander(f"{heading} — {path.name}", expanded=False)' not in MAIN_SOURCE
    assert 'with st.expander(f"Inválido — {path.stem}")' in MAIN_SOURCE
    assert 'with st.expander(f"Ficheiro inválido — {path.stem}")' in MAIN_SOURCE
