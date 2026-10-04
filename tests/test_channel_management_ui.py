from pathlib import Path


def test_channel_cards_show_four_compact_defaults_and_collapsed_videos():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'edit_channel_button_' in source
    assert 'Editar canal' in source
    assert '**Blueprint Padrão**' in source
    assert '**Nicho**' in source
    assert '**Narrador/Voz Padrão**' in source
    assert '**Idioma**' in source
    assert 'with st.expander("Últimos 10 vídeos publicados", expanded=False):' in source
    assert 'Actualizar últimos 10 vídeos' in source
    assert 'st.columns(4, gap="small")' in source


def test_channel_video_views_are_list_only_with_edit_action():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'Apresentação dos canais' not in source
    assert 'youtube_channels_view_mode' not in source
    assert 'render_registered_channels_kanban' not in source
    assert 'Editar vídeo' in source
    assert 'channel_videos.json' in source
    assert 'fetch_channel_videos_public(channel, limit=10)' in source


def test_automation_cards_show_the_same_four_channel_defaults():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    # Commits d62940b/15a2512 ("fix: normalize automation channel card settings"): o
    # default de idioma dos cartões de automação passou a exibir-se como
    # "**Idioma do roteiro**" em vez de "**Idioma Padrão**".
    assert '"**Idioma do roteiro**"' in source
    assert '"Blueprint Padrão"' in source
    assert '"**Nicho Padrão**"' in source
    assert '"Narrador/Voz Padrão"' in source
    assert 'language_label(channel.get("language") or "pt")' in source
    assert 'channel_niche_label(channel)' in source


def test_manual_and_imported_channel_forms_have_niche_field():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'key="yt_import_niche"' in source
    assert 'key="manual_channel_niche"' in source
    assert '"reference_channels"' in source


def test_registered_channels_library_is_only_on_main_channel_page():
    # Commit a701c90 ("fix: show youtube channel library on main page") removeu de
    # propósito a tabela registered_rows (height=420, "Use a barra inferior…") do
    # spreadsheet_tab e moveu a lista de canais cadastrados para a página principal,
    # como biblioteca de cartões editáveis. Este teste verifica a forma actual: a
    # biblioteca aparece uma única vez, fora das tabs de importação, e os cartões
    # mostram os dados dos canais antes exibidos nas colunas da tabela.
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    library_marker = 'st.subheader(f"Canais Youtube cadastrados ({len(channels)})")'
    assert source.count(library_marker) == 1
    spreadsheet_start = source.index("with spreadsheet_tab:")
    batch_start = source.index("with batch_tab:")
    spreadsheet_block = source[spreadsheet_start:batch_start]
    assert library_marker not in spreadsheet_block
    assert "registered_rows" not in source  # a tabela legada não pode voltar silenciosamente
    library_start = source.index(library_marker)
    library_block = source[library_start:source.index("def render_", library_start)]
    assert "channel.get('metrics_source', 'manual')" in library_block  # Origem do canal
    assert 'st.toggle("Activo"' in library_block
    for marker in ("**Blueprint Padrão**", "**Nicho**", "**Narrador/Voz Padrão**", "**Idioma**"):
        assert marker in library_block
    assert '"Conta Google do documento deste canal"' in library_block
    assert '"DELEGATED_SESSION_ID deste canal"' in library_block
