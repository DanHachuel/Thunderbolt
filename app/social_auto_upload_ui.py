from __future__ import annotations

from typing import Any

import streamlit as st

from hermes_ui.browser_manager import get_available_browsers, get_browser_status, has_gui_environment
from hermes_ui.proxy_manager import add_proxy, list_proxies, remove_proxy, set_active_proxy, test_proxy, update_proxy
from hermes_ui.social_auto_upload_backend import (
    add_sau_account,
    check_platform_session,
    get_platform_uploaders,
    get_sau_cookie_path,
    get_sau_install_status,
    list_sau_accounts,
    login_platform,
    login_youtube_session,
    remove_sau_account,
    session_state_path,
    validate_storage_state,
)
from hermes_ui.storage import read_json, update_json


def _save_browser_settings(enabled: bool, browser_type: str, geoip: bool) -> None:
    def mutate(settings: Any) -> None:
        if not isinstance(settings, dict):
            return
        settings["social_auto_upload_enabled"] = bool(enabled)
        settings["social_auto_upload_browser"] = str(browser_type)
        settings["social_auto_upload_geoip"] = bool(geoip)

    update_json("settings.json", {}, mutate)


def _status_message(status: dict[str, str]) -> None:
    message = str(status.get("message") or "Sem informação de estado.")
    if status.get("status") == "installed":
        st.success(message)
    elif status.get("status") == "not_installed":
        st.warning(message)
    else:
        st.error(message)


def render_social_auto_upload_settings() -> None:
    settings = read_json("settings.json", {})
    if not isinstance(settings, dict):
        settings = {}

    st.subheader("Navegador do upload directo YouTube")
    st.caption("Esta selecção controla apenas o browser da integração directa YouTube: uploads headless por instância e login visível com timeout de 5 minutos. Os outros destinos social-auto-upload usam a CLI upstream com Patchright/Chromium.")
    with st.form("social_auto_upload_browser_settings"):
        enabled = st.checkbox(
            "Permitir fallback social-auto-upload na pipeline YouTube",
            value=bool(settings.get("social_auto_upload_enabled", True)),
        )
        browser_options = get_available_browsers()
        browser_ids = [item["type"] for item in browser_options]
        current_browser = str(settings.get("social_auto_upload_browser") or "camoufox").casefold()
        browser_index = browser_ids.index(current_browser) if current_browser in browser_ids else 0
        browser_type = st.selectbox(
            "Browser do upload directo YouTube",
            browser_ids,
            index=browser_index,
            format_func=lambda value: next((item["label"] for item in browser_options if item["type"] == value), value),
        )
        geoip = st.checkbox(
            "Usar GeoIP no Camoufox",
            value=bool(settings.get("social_auto_upload_geoip", True)),
            help="Quando há proxy, o endereço de saída desse proxy é a referência do spoofing. Se GeoIP falhar com SOCKS5, o browser inicia sem spoofing e regista um aviso.",
        )
        save_browser = st.form_submit_button("Guardar configuração do browser", type="primary")
    if save_browser:
        _save_browser_settings(enabled, browser_type, geoip)
        st.success("Configuração guardada sem alterar os restantes settings.")

    if st.button("Testar instalação do browser", key="social_auto_upload_test_browser"):
        with st.spinner("A testar import, binário e lançamento do browser…"):
            _status_message(get_browser_status(browser_type))

    state_path = session_state_path()
    session_ok, session_message = validate_storage_state(state_path, "youtube.com")
    if session_ok:
        st.success("Sessão YouTube validada. Os cookies ficam apenas no storage local.")
    else:
        st.info(f"{session_message} Pode continuar a usar o Thunderbolt sem configurar um canal. Local esperado: `{state_path}`")
    if not has_gui_environment():
        st.warning("Este ambiente não detectou GUI. O login visível requer Windows/desktop, VNC ou X11 forwarding; depois copie storage_state.json para o caminho local mostrado acima.")
    if st.button("Iniciar login visível no YouTube", key="social_auto_upload_login"):
        with st.spinner("A aguardar o login no browser visível (máximo de 5 minutos)…"):
            result = login_youtube_session(browser_type=browser_type, timeout_seconds=300)
        if result.get("success"):
            st.success(str(result.get("message") or "Login guardado."))
        else:
            st.error(str(result.get("message") or "O login falhou."))

    st.divider()
    st.subheader("Proxies")
    st.caption("A lista pode ficar vazia: nesse caso os browsers continuam sem proxy e nenhuma acção de configuração é bloqueada.")
    proxies = list_proxies()
    current_settings = read_json("settings.json", {})
    active_id = str(current_settings.get("proxy_active_id") or "") if isinstance(current_settings, dict) else ""
    option_ids = [""] + [str(card.get("id") or "") for card in proxies]
    labels = {str(card.get("id") or ""): f"{card.get('label') or 'Proxy'} · {card.get('server') or ''}" for card in proxies}
    selected_active = st.selectbox(
        "Proxy activo",
        option_ids,
        index=option_ids.index(active_id) if active_id in option_ids else 0,
        format_func=lambda value: "Sem proxy" if not value else labels.get(value, "Proxy"),
        key="social_auto_upload_active_proxy",
    )
    if st.button("Aplicar proxy activo", key="social_auto_upload_apply_proxy"):
        if set_active_proxy(selected_active or None):
            st.success("Proxy activo actualizado. Omitir a configuração mantém a ligação directa.")
        else:
            st.error("Não foi possível seleccionar esse proxy; confirme se ainda está na lista.")

    with st.form("social_auto_upload_add_proxy"):
        st.markdown("**Adicionar proxy**")
        add_cols = st.columns(4)
        with add_cols[0]:
            new_label = st.text_input("Nome", value="Proxy", key="social_proxy_new_label")
        with add_cols[1]:
            new_scheme = st.selectbox("Tipo", ["http", "https", "socks5"], key="social_proxy_new_scheme")
        with add_cols[2]:
            new_host = st.text_input("Host", key="social_proxy_new_host")
            new_port = st.number_input("Porta", min_value=1, max_value=65535, value=8080, key="social_proxy_new_port")
        with add_cols[3]:
            new_username = st.text_input("Utilizador (opcional)", key="social_proxy_new_username")
            new_password = st.text_input("Palavra-passe (opcional)", type="password", key="social_proxy_new_password")
        add_proxy_clicked = st.form_submit_button("Adicionar proxy")
    if add_proxy_clicked:
        try:
            host = str(new_host or "").strip()
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            add_proxy(
                new_label,
                f"{new_scheme}://{host}:{int(new_port)}",
                proxy_type=new_scheme,
                username=new_username,
                password=new_password,
            )
            st.success("Proxy guardado localmente.")
            st.rerun()
        except Exception as exc:
            st.error(f"Proxy inválido: {exc}")

    if not proxies:
        st.caption("Nenhum proxy cadastrado. Continue a trabalhar sem proxy ou adicione um acima.")
    for card in proxies:
        proxy_id = str(card.get("id") or "")
        with st.container(border=True):
            title_cols = st.columns([3, 1])
            with title_cols[0]:
                st.write(f"**{card.get('label') or 'Proxy'}** · {card.get('scheme') or 'http'} · {card.get('server') or ''}")
                if card.get("has_credentials"):
                    st.caption(f"Credenciais guardadas · utilizador {card.get('username_display') or '—'} · palavra-passe oculta")
                last_test = card.get("last_test")
                if isinstance(last_test, dict) and last_test.get("message"):
                    st.caption(f"Último teste: {last_test.get('message')}" + (f" IP {last_test.get('ip')}" if last_test.get("ip") else ""))
            with title_cols[1]:
                if card.get("active"):
                    st.success("Activo")
            action_cols = st.columns(3)
            with action_cols[0]:
                if st.button("Testar proxy", key=f"social_proxy_test_{proxy_id}"):
                    with st.spinner("A testar o IP de saída (timeout 10 s)…"):
                        result = test_proxy(proxy_id)
                    (st.success if result.get("status") == "ok" else st.error)(
                        str(result.get("message") or "Teste concluído.") + (f" IP de saída: {result['ip']}" if result.get("ip") else "")
                    )
            with action_cols[1]:
                if st.button("Activar", key=f"social_proxy_activate_{proxy_id}"):
                    set_active_proxy(proxy_id)
                    st.rerun()
            with action_cols[2]:
                if st.button("Remover", key=f"social_proxy_remove_{proxy_id}"):
                    remove_proxy(proxy_id)
                    st.rerun()
            with st.expander(f"Editar {card.get('label') or 'proxy'}", expanded=False):
                with st.form(f"social_proxy_edit_{proxy_id}"):
                    edit_label = st.text_input("Nome", value=str(card.get("label") or "Proxy"), key=f"social_proxy_edit_label_{proxy_id}")
                    scheme_options = ["http", "https", "socks5", "socks5h"]
                    saved_scheme = str(card.get("scheme") or "http").casefold()
                    if saved_scheme not in scheme_options:
                        saved_scheme = "http"
                    edit_scheme = st.selectbox("Tipo", scheme_options, index=scheme_options.index(saved_scheme), key=f"social_proxy_edit_scheme_{proxy_id}")
                    edit_server = st.text_input("Servidor", value=str(card.get("server") or ""), key=f"social_proxy_edit_server_{proxy_id}")
                    edit_username = st.text_input("Novo utilizador (opcional)", key=f"social_proxy_edit_username_{proxy_id}")
                    edit_password = st.text_input("Nova palavra-passe (opcional)", type="password", key=f"social_proxy_edit_password_{proxy_id}")
                    clear_credentials = st.checkbox("Limpar credenciais guardadas", key=f"social_proxy_clear_{proxy_id}")
                    edit_enabled = st.checkbox("Proxy activo para uso", value=bool(card.get("enabled", True)), key=f"social_proxy_enabled_{proxy_id}")
                    save_proxy = st.form_submit_button("Guardar edição")
                if save_proxy:
                    updates: dict[str, Any] = {"label": edit_label, "server": edit_server, "scheme": edit_scheme, "enabled": edit_enabled}
                    if clear_credentials:
                        updates.update({"username": "", "password": ""})
                    else:
                        if edit_username:
                            updates["username"] = edit_username
                        if edit_password:
                            updates["password"] = edit_password
                    try:
                        update_proxy(proxy_id, **updates)
                        st.success("Proxy actualizado.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível actualizar o proxy: {exc}")



def render_sau_accounts() -> None:
    """Render account/session management for the upstream social-auto-upload CLI."""
    rows = get_platform_uploaders()
    labels = {row["platform"]: row["label"] for row in rows}
    matrix = [
        {
            "Plataforma": row["label"],
            "Estado": "Disponível no CLI upstream",
            "Browser": row["browser"],
            "Login": "Terminal interactivo" if row["login_mode"] == "terminal" else "Browser visível",
        }
        for row in rows
    ]
    matrix.append({"Plataforma": "TikTok", "Estado": "Indisponível no CLI upstream", "Browser": "—", "Login": "Use a integração TikTok existente"})
    st.caption("As plataformas CLI suportadas usam o `sau` upstream com Patchright/Chromium. Este painel não altera o upload directo YouTube, que mantém a sessão Camoufox configurada em Navegador e Proxies.")
    st.dataframe(matrix, hide_index=True, width="stretch")
    st.info("YouTube directo continua separado. A conta YouTube aqui é apenas para a CLI upstream opcional; não substitui cookies nem a sessão do upload directo Camoufox.")
    st.warning("Bilibili abre um terminal interactivo para o login. Em ambiente headless, faça login num desktop/terminal com GUI e copie o cookie para o caminho local mostrado no cartão.")

    if st.button("Testar instalação da CLI social-auto-upload", key="sau_cli_test_install"):
        status = get_sau_install_status()
        if status.get("installed"):
            st.success(f"{status['message']} Python {status.get('python')}.")
        else:
            st.warning(f"{status.get('message')} Python detectado: {status.get('python')}.")

    with st.form("sau_add_account_form"):
        st.markdown("**Adicionar conta social**")
        add_cols = st.columns([1.2, 1.2, 1.2, 1])
        with add_cols[0]:
            selected_platform = st.selectbox("Plataforma", [row["platform"] for row in rows], format_func=lambda value: labels.get(value, value), key="sau_new_platform")
        with add_cols[1]:
            account_name = st.text_input("Nome da conta upstream", key="sau_new_account_name", help="Use letras, números, ponto, hífen ou underscore; não precisa ser um utilizador/e-mail da plataforma.")
        with add_cols[2]:
            account_label = st.text_input("Nome visível (opcional)", key="sau_new_account_label")
        with add_cols[3]:
            add_clicked = st.form_submit_button("Adicionar conta", type="primary", width="stretch")
    if add_clicked:
        try:
            account = add_sau_account(selected_platform, account_name, account_label)
            st.success(f"Conta {account['label']} adicionada. O login só é necessário quando clicar em Login ou verificar a sessão.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    accounts = list_sau_accounts()
    if not accounts:
        st.info("Ainda não há contas social-auto-upload. Pode continuar a usar as restantes áreas do Thunderbolt e adicionar uma conta quando precisar.")
        return
    st.markdown("**Contas e sessões**")
    for item in accounts:
        platform = item["platform"]
        account_name = item["account_name"]
        account_key = f"{platform}_{account_name}".replace(".", "_").replace("-", "_")
        cookie_path = get_sau_cookie_path(platform, account_name)
        with st.container(border=True):
            cols = st.columns([2.3, 1.6, 1.1, 1.1, 0.9])
            with cols[0]:
                st.write(f"**{item['label']}** · {labels.get(platform, platform)}")
                st.caption(f"Conta upstream: `{account_name}`")
                st.caption(f"Cookie local: `{cookie_path}` · {'ficheiro presente' if cookie_path.is_file() else 'ainda não criado'}")
            with cols[1]:
                if platform == "bilibili":
                    st.caption("Login em terminal visível")
                elif platform == "youtube":
                    st.caption("Sessão CLI separada do YouTube directo")
                else:
                    st.caption("Login em browser visível")
            with cols[2]:
                if st.button("Login", key=f"sau_login_{account_key}", width="stretch"):
                    with st.spinner("A abrir a sessão de login social-auto-upload…"):
                        login = login_platform(platform, account_name, timeout_seconds=300)
                    if login.get("success"):
                        st.success(str(login.get("message") or "Login iniciado."))
                        if login.get("cookie_path"):
                            st.caption(f"Cookie: `{login['cookie_path']}`")
                    else:
                        st.warning(str(login.get("message") or "Não foi possível iniciar o login."))
                        if login.get("cookie_path"):
                            st.caption(f"Caminho esperado: `{login['cookie_path']}`")
            with cols[3]:
                if st.button("Verificar", key=f"sau_check_{account_key}", width="stretch"):
                    with st.spinner("A verificar a sessão com a CLI upstream…"):
                        checked = check_platform_session(platform, account_name)
                    (st.success if checked.get("valid") else st.warning)(str(checked.get("message") or "A verificação não foi concluída."))
            with cols[4]:
                if st.button("Remover", key=f"sau_remove_{account_key}", width="stretch", help="Remove a conta da lista; não apaga o cookie local."):
                    remove_sau_account(platform, account_name)
                    st.rerun()
