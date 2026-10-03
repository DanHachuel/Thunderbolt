from pathlib import Path


MAIN_SOURCE = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")


def test_direct_credentials_keep_cookies_in_document_but_api_key_in_account_section():
    assert 'Subir documento de cookies/credenciais' in MAIN_SOURCE
    assert 'Aceita o JSON do YouTube-Video-Upload-Frontend-Api' in MAIN_SOURCE
    assert 'Guardar documento nesta conta' in MAIN_SOURCE
    assert 'credentials.json' in MAIN_SOURCE
    assert '### INNERTUBE_API_KEY' in MAIN_SOURCE
    assert 'Guardar INNERTUBE_API_KEY' in MAIN_SOURCE
    # Commit 7e10f82 ("fix: make INNERTUBE_API_KEY global"): a ajuda do campo passou a
    # dizer "separada dos documentos de cookies." em vez de "fora do documento de cookies.".
    assert 'separada dos documentos de cookies.' in MAIN_SOURCE


def test_direct_credentials_are_read_per_account_and_channel_from_document():
    assert 'credentials_document_path' in MAIN_SOURCE or 'credentials.json' in MAIN_SOURCE
    assert 'document_status(STORAGE, selected_channel_account, channel, settings, channels)' in MAIN_SOURCE
    assert 'delegated_session_ids' in MAIN_SOURCE
    assert 'st.text_input("DELEGATED_SESSION_ID deste canal (individual)"' not in MAIN_SOURCE
    assert 'sessionInfo token desta conta Google' in MAIN_SOURCE
    # Commit 681f997 ("fix: collapse new Google account form by default"): a secção de
    # nova conta passou a ser aberta pelo botão "Adicionar conta Google/YouTube" e o
    # formulário externo passou a intitular-se "### Nova conta Gmail".
    assert 'Adicionar conta Google/YouTube' in MAIN_SOURCE
    assert '### Nova conta Gmail' in MAIN_SOURCE
    assert 'Apagar conta' in MAIN_SOURCE
    assert 'merge_credentials_document' in MAIN_SOURCE
    assert 'Documento incompleto:' in MAIN_SOURCE
    assert 'st.file_uploader("Ficheiro de cookies desta conta Google"' not in MAIN_SOURCE
    assert 'text_setting("INNERTUBE_API_KEY"' not in MAIN_SOURCE
    assert 'direct_innertube_api_key = str(settings.get("direct_innertube_api_key"' not in MAIN_SOURCE
    assert 'st.caption("As credenciais e parâmetros do Upload directo — cookies, sessionInfo, INNERTUBE_API_KEY' not in MAIN_SOURCE
    assert 'number_input("Chunk size' not in MAIN_SOURCE
    assert 'redirect_uri_mismatch' in MAIN_SOURCE or 'loopback_redirect_uri' in MAIN_SOURCE


def test_innertube_key_block_is_between_account_status_and_add_account():
    status_marker = 'Contas que ainda precisam de dados no documento:'
    key_marker = '### INNERTUBE_API_KEY'
    # Commit 681f997 ("fix: collapse new Google account form by default"): a secção de
    # nova conta é aberta pelo botão "Adicionar conta Google/YouTube".
    add_marker = 'Adicionar conta Google/YouTube'
    assert MAIN_SOURCE.index(status_marker) < MAIN_SOURCE.index(key_marker) < MAIN_SOURCE.index(add_marker)
    assert 'with st.form("innertube_api_key_form")' in MAIN_SOURCE
    # Commit 7e10f82 ("fix: make INNERTUBE_API_KEY global"): o campo deixou de ter key
    # por conta (innertube_api_key_{selected_key_account_id}) e passou a usar key global fixa.
    assert 'key="global_innertube_api_key"' in MAIN_SOURCE


def test_google_accounts_use_collapsed_name_email_cards_and_external_add_form():
    # Commit e87f885 ("feat: reorganize Google accounts as collapsible cards with auto
    # credentials.json"): o cartão passou a ser um container com borda; o cabeçalho
    # "nome — e-mail" é um subheader e os dados editáveis ficam no expander recolhido.
    assert 'st.subheader(f"{account_label_snapshot} — {account_email_snapshot}")' in MAIN_SOURCE
    assert 'with st.expander("Detalhes da conta Google", expanded=False):' in MAIN_SOURCE
    assert 'st.divider()' in MAIN_SOURCE
    assert 'with st.form("add_batch_account_form")' in MAIN_SOURCE
    assert 'ensure_credentials_document(STORAGE, batch_account, settings, channel_state)' in MAIN_SOURCE
    assert 'associação de canais não depende da completude deste documento' in MAIN_SOURCE


def test_api_settings_keep_api_keys_and_voice_test_tabs():
    # Commits 503cf95/628d807 ("feat: organize technical settings into tabs" /
    # "Fix API settings tabs and read-only engine path"): a lista de tabs de
    # render_settings cresceu e "Teste de vozes" passou a "Teste de Voz"; as duas
    # tabs verificadas (API Keys e teste de voz) continuam presentes.
    expected = 'render_localized_tabs(["API Keys", "API Keys Upload", "Legendas", "FFmpeg", "AI Influencers", "Test Upload Videos", "Teste de Voz", "Navegador e Proxies"])'
    assert expected in MAIN_SOURCE
    assert 'st.subheader("API Keys")' in MAIN_SOURCE
    assert 'st.subheader("Execução local")' not in MAIN_SOURCE


def test_legacy_cookie_inputs_are_not_rendered():
    for label in ("SID global legado", "SSID global legado", "HSID global legado", "APISID global legado", "SAPISID global legado", "sessionInfo token global legado"):
        assert label not in MAIN_SOURCE
