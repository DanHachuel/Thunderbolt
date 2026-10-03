from pathlib import Path


def test_youtube_channel_delete_ui_has_confirmation_and_persistence_call():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    start = source.index('delete_key = f"delete_pending_{channel_id}"')
    # Commit da55713 ("feat: add searchable expandable channel cards") moveu a acção de
    # apagar para dentro do expander "Detalhes e configuração do canal", depois do bloco
    # de edição; o fluxo de delete termina agora na preparação das contas Google do canal.
    end = source.index('channel_account_ids = list(youtube_account_ids)', start)
    block = source[start:end]
    assert 'st.session_state[delete_key] = True' in block
    assert 'st.button("Confirmar apagar"' in block
    assert 'removed = delete_channel(channel_id)' in block
    assert 'st.button("Cancelar"' in block
    assert 'st.rerun()' in block


def test_youtube_channel_page_filters_channel_loop_from_shared_youtube_filter():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    start = source.index('def render_channels():')
    end = source.index('def render_', start + 20)
    block = source[start:end]
    # Commit a701c90 ("fix: show youtube channel library on main page") removeu a tabela
    # registered_rows e consolidou a filtragem num único ponto partilhado: a mesma lista
    # filtrada alimenta a contagem do subheader, a pesquisa e o loop de cartões.
    expected = 'is_youtube_channel_record(channel)'
    assert block.count(expected) == 1
    assert 'channels = [channel for channel in read_json("channels.json", []) if is_youtube_channel_record(channel)]' in block
    assert 'for channel in visible_registered_channels:' in block
    assert '\n    channels = read_json("channels.json", [])' not in block
