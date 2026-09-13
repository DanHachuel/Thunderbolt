from __future__ import annotations

import io
import re
import uuid
import zipfile
import unicodedata
from pathlib import Path
from typing import Any, Callable, Mapping

import requests
import streamlit as st

from hermes_ui.domain import create_channel, delete_channel, update_channel
from hermes_ui.influencers import InfluencerBackendError, STANDALONE_CONTENT_INFLUENCER_ID, get_repository
from hermes_ui.storage import STORAGE, TIKTOK_PROMPT_MASTERS, list_prompt_master_files, read_json, write_json
from hermes_ui.countries import COUNTRY_OPTIONS
from hermes_ui.languages import LANGUAGE_CODES, language_code, language_label
from integrations.instagram_public import fetch_public_instagram_posts, fetch_public_instagram_profile, normalize_instagram_metric
from integrations.meta_social import test_facebook_pages_api_card, test_instagram_api_card


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _metric(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return _clean(value) or "—"


INSTAGRAM_MODEL_OPTIONS = (
    "Prompt-Masters Tiktok",
    "Facebook Blueprint",
    "Personagens Influencer/UGC",
)


def _instagram_model_options(settings: Mapping[str, Any], model_type: str) -> tuple[list[str], dict[str, str]]:
    """Return the dependent model list for an Instagram account."""
    if model_type == "Prompt-Masters Tiktok":
        files = list_prompt_master_files()
        values = [path.name for path in files]
        return values, {path.name: path.stem for path in files}
    if model_type == "Facebook Blueprint":
        root = STORAGE / "facebook" / "blueprints"
        root.mkdir(parents=True, exist_ok=True)
        files = sorted(root.glob("*.md")) if root.is_dir() else []
        values = [path.name for path in files]
        return values, {path.name: path.stem for path in files}
    characters, _ = _characters(settings)
    values = [_clean(item.get("id")) for item in characters if _clean(item.get("id"))]
    return values, {_clean(item.get("id")): _clean(item.get("name")) or _clean(item.get("id")) for item in characters if _clean(item.get("id"))}


def resolve_instagram_model(profile: Mapping[str, Any], settings: Mapping[str, Any]) -> dict[str, str]:
    """Resolve the model attached to an Instagram profile for automation."""
    model_type = _clean(profile.get("instagram_model_type") or profile.get("model_type")) or INSTAGRAM_MODEL_OPTIONS[2]
    if model_type not in INSTAGRAM_MODEL_OPTIONS:
        model_type = INSTAGRAM_MODEL_OPTIONS[2]
    model_id = _clean(profile.get("instagram_model_id") or profile.get("model_id"))
    options, labels = _instagram_model_options(settings, model_type)
    if model_id and model_id not in options:
        model_id = ""
    return {"type": model_type, "id": model_id, "label": labels.get(model_id, model_id or "Sem modelo seleccionado")}


def _render_instagram_model_selector(profile: Mapping[str, Any], settings: Mapping[str, Any], *, key_prefix: str) -> tuple[str, str]:
    current = resolve_instagram_model(profile, settings)
    model_type = st.selectbox(
        "Atrelar modelo",
        list(INSTAGRAM_MODEL_OPTIONS),
        index=list(INSTAGRAM_MODEL_OPTIONS).index(current["type"]),
        key=f"{key_prefix}_model_type",
        help="A conta pode usar Prompt-Masters Tiktok, Facebook Blueprint ou Personagens Influencer/UGC.",
    )
    options, labels = _instagram_model_options(settings, model_type)
    model_id = st.selectbox(
        "Modelo/Blueprint",
        [""] + options,
        index=options.index(current["id"]) + 1 if current["id"] in options else 0,
        format_func=lambda value: "Sem modelo seleccionado" if not value else labels.get(value, value),
        key=f"{key_prefix}_model_id",
    )
    return model_type, model_id


def _profile_metric(profile: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = profile.get(key)
        normalized = normalize_instagram_metric(value)
        if normalized is not None:
            return normalized
    return None


def _metric_input(value: Any) -> int | None:
    return normalize_instagram_metric(value)


def _render_instagram_bio(value: Any) -> None:
    bio = str(value or "")
    if bio:
        st.text(bio)


def _profile_bio(profile: Mapping[str, Any]) -> str:
    return str(profile.get("bio") or profile.get("biography", ""))


def _country_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", _clean(value))
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


COUNTRY_CODE_NAMES = {
    "BR": "Brasil",
    "CH": "Suíça",
    "ES": "Espanha",
    "RS": "Sérvia",
}


COUNTRY_NAME_CODES = {name: code for code, name in COUNTRY_CODE_NAMES.items()}


def _country_flag(value: Any) -> str:
    """Render a two-letter country code as a Unicode regional-indicator flag."""
    clean_value = _clean(value).upper()
    if len(clean_value) != 2 or not clean_value.isascii() or not clean_value.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in clean_value)


def _country_display(value: Any) -> str:
    clean_value = _clean(value)
    if not clean_value:
        return "Não definido"
    code = clean_value.upper()
    flag = _country_flag(code)
    if flag:
        return f"{flag} {COUNTRY_CODE_NAMES.get(code, code)}"
    mapped_code = COUNTRY_NAME_CODES.get(clean_value)
    return f"{_country_flag(mapped_code)} {clean_value}" if mapped_code else clean_value


COUNTRY_ALIASES = {
    "brazil": "Brasil",
    "brasil": "Brasil",
    "usa": "Estados Unidos",
    "us": "Estados Unidos",
    "united states": "Estados Unidos",
    "united states of america": "Estados Unidos",
    "portugal": "Portugal",
}


def _normalise_country(value: Any) -> str:
    clean_value = _clean(value)
    if not clean_value:
        return ""
    code = clean_value.upper()
    if code in COUNTRY_CODE_NAMES:
        return COUNTRY_CODE_NAMES[code]
    if len(code) == 2 and code.isascii() and code.isalpha():
        # Keep unknown legacy ISO codes usable and renderable rather than dropping them.
        return code
    if clean_value in COUNTRY_OPTIONS:
        return clean_value
    key = _country_key(clean_value)
    for country in COUNTRY_OPTIONS:
        if _country_key(country) == key:
            return country
    return COUNTRY_ALIASES.get(key, "")


def _profile_country(profile: Mapping[str, Any]) -> str:
    for key in ("country", "country_name", "country_of_registration", "account_country", "account_based_in"):
        country = _normalise_country(profile.get(key))
        if country:
            return country
    return ""


def _language_index(value: Any) -> int:
    code = language_code(value)
    return list(LANGUAGE_CODES).index(code) if code in LANGUAGE_CODES else list(LANGUAGE_CODES).index("pt")


def _country_options() -> tuple[str, ...]:
    return ("",) + COUNTRY_OPTIONS


def _country_index(value: Any) -> int:
    options = _country_options()
    value = _normalise_country(value)
    return options.index(value) if value in options else 0


def _country_label(value: str) -> str:
    return _country_display(value)


def _instagram_posts_key(profile_id: str) -> str:
    return f"instagram_posts_{profile_id}"


def _instagram_profile_storage_id(profile: Mapping[str, Any]) -> str:
    value = _clean(profile.get("id")) or _clean(profile.get("username")) or _clean(profile.get("handle")).lstrip("@") or _clean(profile.get("url"))
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value) or "unknown"


def _normalise_instagram_posts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(post) for post in value if isinstance(post, Mapping) and _clean(post.get("id") or post.get("url"))]


def _stored_instagram_posts(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    profile_id = _instagram_profile_storage_id(profile)
    state_key = _instagram_posts_key(profile_id)
    posts = _normalise_instagram_posts(st.session_state.get(state_key, []))
    if posts:
        return posts
    for key in ("instagram_posts", "recent_posts", "posts"):
        posts = _normalise_instagram_posts(profile.get(key))
        if posts:
            st.session_state[state_key] = posts
            return posts
    stored = read_json("instagram_posts.json", {})
    if isinstance(stored, dict):
        posts = _normalise_instagram_posts(stored.get(profile_id))
        if posts:
            st.session_state[state_key] = posts
    return posts


def _persist_instagram_posts(profile: Mapping[str, Any], posts: list[dict[str, Any]]) -> None:
    profile_id = _instagram_profile_storage_id(profile)
    stored = read_json("instagram_posts.json", {})
    if not isinstance(stored, dict):
        stored = {}
    stored[profile_id] = _normalise_instagram_posts(posts)
    write_json("instagram_posts.json", stored)
    st.session_state[_instagram_posts_key(profile_id)] = stored[profile_id]


def _instagram_posts_archive(posts: list[dict[str, Any]]) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        manifest: list[str] = []
        for index, post in enumerate(posts, start=1):
            url = _clean(post.get("image_url"))
            if url:
                try:
                    response = requests.get(url, timeout=15)
                    response.raise_for_status()
                    extension = ".jpg"
                    content_type = response.headers.get("content-type", "")
                    if "png" in content_type:
                        extension = ".png"
                    elif "webp" in content_type:
                        extension = ".webp"
                    bundle.writestr(f"post-{index:02d}{extension}", response.content)
                except requests.RequestException:
                    pass
            manifest.append(f"{index}. {_clean(post.get('url'))}\n{_clean(post.get('caption'))}\n")
        bundle.writestr("posts.txt", "\n".join(manifest))
    return archive.getvalue()


def _render_instagram_posts(profile: Mapping[str, Any]) -> None:
    profile_id = _instagram_profile_storage_id(profile)
    state_key = _instagram_posts_key(profile_id)
    posts = _stored_instagram_posts(profile)
    with st.expander("Últimos posts do Instagram", expanded=False):
        action_cols = st.columns(3)
        with action_cols[0]:
            load_clicked = st.button("Carregar últimos 10", key=f"load_instagram_posts_{profile_id}", width="stretch")
        with action_cols[1]:
            refresh_clicked = st.button("Actualizar tudo", key=f"refresh_instagram_posts_{profile_id}", width="stretch")
        with action_cols[2]:
            download_clicked = bool(posts) and st.download_button("Baixar todos", data=_instagram_posts_archive(posts), file_name=f"instagram-{profile_id}-posts.zip", mime="application/zip", key=f"download_instagram_posts_{profile_id}", width="stretch")
        if load_clicked or refresh_clicked:
            target = max(10, len(posts)) if refresh_clicked else 10
            posts_ok, posts_message, loaded_posts = _load_instagram_posts(profile, limit=target)
            st.write(f"Resultado do posts: {posts_ok}, mensagem: {posts_message}")
            st.write(f"Posts retornados: {len(loaded_posts)}")
            if posts_ok:
                posts = loaded_posts
                _persist_instagram_posts(profile, posts)
                st.success(f"{len(posts)} posts carregados.")
                st.rerun()
            else:
                st.warning(posts_message)
        posts = st.session_state.get(state_key, posts)
        if not posts:
            st.info("Clique em Carregar últimos 10 para consultar os posts públicos desta conta.")
            return
        for post in posts:
            with st.container(border=True):
                post_cols = st.columns([1, 3])
                with post_cols[0]:
                    if _clean(post.get("image_url")):
                        st.image(post["image_url"], width="stretch")
                with post_cols[1]:
                    if _clean(post.get("url")):
                        st.link_button("Abrir post", post["url"])
                    if _clean(post.get("caption")):
                        st.caption(post["caption"])
        if st.button("Mostrar + 10", key=f"more_instagram_posts_{profile_id}", width="stretch"):
            posts_ok, posts_message, loaded_posts = _load_instagram_posts(profile, limit=len(posts) + 10)
            if posts_ok:
                _persist_instagram_posts(profile, loaded_posts)
                st.rerun()
            st.write(f"Resultado do posts: {posts_ok}, mensagem: {posts_message}")
            st.write(f"Posts retornados: {len(loaded_posts)}")
            st.warning(posts_message)


def _api_card_defaults(kind: str) -> tuple[str, list[str], Callable[[Mapping[str, Any]], dict[str, Any]]]:
    if kind == "instagram":
        return "instagram_api_cards", ["id", "label", "account_id", "access_token"], test_instagram_api_card
    return "facebook_pages_api_cards", ["id", "label", "page_id", "access_token"], test_facebook_pages_api_card


def _normalise_api_cards(settings: dict[str, Any], kind: str) -> list[dict[str, str]]:
    key, fields, _ = _api_card_defaults(kind)
    raw = settings.get(key)
    cards: list[dict[str, str]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            card = {field: _clean(item.get(field)) for field in fields}
            card["id"] = card["id"] or f"{kind}-api-{index + 1}"
            cards.append(card)
    if not cards:
        legacy_key = "instagram_api_key" if kind == "instagram" else "facebook_pages_api_key"
        legacy_id = "instagram_account_id" if kind == "instagram" else "facebook_page_id"
        token = _clean(settings.get(legacy_key))
        identifier = _clean(settings.get(legacy_id))
        if token or identifier:
            cards = [{"id": f"{kind}-api-1", "label": "Conta 1", "account_id" if kind == "instagram" else "page_id": identifier, "access_token": token}]
    if cards and not isinstance(raw, list):
        settings[key] = cards
        write_json("settings.json", settings)
    return cards


def _persist_api_cards(settings: dict[str, Any], kind: str, cards: list[dict[str, Any]]) -> None:
    key, fields, _ = _api_card_defaults(kind)
    clean_cards: list[dict[str, str]] = []
    for index, item in enumerate(cards):
        card = {field: _clean(item.get(field)) for field in fields}
        card["id"] = card["id"] or f"{kind}-api-{index + 1}"
        clean_cards.append(card)
    settings[key] = clean_cards
    if kind == "instagram":
        first = next((item for item in clean_cards if item.get("account_id") and item.get("access_token")), clean_cards[0] if clean_cards else {})
        settings["instagram_account_id"] = first.get("account_id", "")
        settings["instagram_api_key"] = first.get("access_token", "")
    else:
        first = next((item for item in clean_cards if item.get("page_id") and item.get("access_token")), clean_cards[0] if clean_cards else {})
        settings["facebook_page_id"] = first.get("page_id", "")
        settings["facebook_pages_api_key"] = first.get("access_token", "")
    write_json("settings.json", settings)


def _api_card_status(card: Mapping[str, Any], kind: str) -> tuple[str, str]:
    identifier = _clean(card.get("account_id" if kind == "instagram" else "page_id"))
    token = _clean(card.get("access_token"))
    if not token:
        return "missing", "Missing key"
    if not identifier:
        return "missing", "Missing configuration"
    return "ready", "Configured"


def render_meta_api_cards(settings: dict[str, Any], kind: str) -> None:
    is_instagram = kind == "instagram"
    title = "API Instagram" if is_instagram else "API Facebook Pages"
    entity_label = "Instagram Account ID" if is_instagram else "Facebook Page ID"
    key, _, tester = _api_card_defaults(kind)
    cards = _normalise_api_cards(settings, kind)
    if not cards:
        st.info(f"Ainda não existe nenhuma conta {title.replace('API ', '')} configurada. Use o botão abaixo para criar o primeiro card.")
    for index, card in enumerate(cards):
        card_id = _clean(card.get("id"))
        status_kind, status_label = _api_card_status(card, kind)
        with st.container(border=True):
            header_cols = st.columns([3.2, 1.2])
            with header_cols[0]:
                st.subheader(f"{title} {index + 1}")
                st.caption("Cada card representa uma conta independente; o token é guardado apenas no storage local.")
            with header_cols[1]:
                st.markdown(
                    f'<span class="tb-api-status tb-api-status--{status_kind}">{"✓" if status_kind == "ready" else "!"} {status_label}</span>',
                    unsafe_allow_html=True,
                )
            with st.form(f"{kind}_api_card_form_{card_id}"):
                label = st.text_input("Nome da conta", value=_clean(card.get("label")) or f"Conta {index + 1}", key=f"{kind}_api_{card_id}_label")
                identifier = st.text_input(entity_label, value=_clean(card.get("account_id" if is_instagram else "page_id")), key=f"{kind}_api_{card_id}_identifier")
                token = st.text_input("Access Token", value=_clean(card.get("access_token")), type="password", key=f"{kind}_api_{card_id}_token")
                action_cols = st.columns(3)
                with action_cols[0]:
                    test_clicked = st.form_submit_button("Teste chamada API", width="stretch")
                with action_cols[1]:
                    save_clicked = st.form_submit_button("Guardar Card", type="primary", width="stretch")
                with action_cols[2]:
                    delete_clicked = st.form_submit_button("Apagar Card", width="stretch")
            edited = {
                "id": card_id,
                "label": label.strip(),
                "access_token": token.strip(),
                ("account_id" if is_instagram else "page_id"): identifier.strip(),
            }
            if test_clicked:
                cards[index] = edited
                _persist_api_cards(settings, kind, cards)
                result = tester(edited)
                if result.get("status") == "success":
                    st.success(result.get("message") or "Chamada API concluída.")
                elif result.get("status") == "missing":
                    st.warning(result.get("message") or "Missing configuration")
                else:
                    st.error(result.get("message") or "A chamada API falhou.")
            elif save_clicked:
                cards[index] = edited
                _persist_api_cards(settings, kind, cards)
                st.success(f"{title} guardada.")
                st.rerun()
            elif delete_clicked:
                cards = [item for item in cards if _clean(item.get("id")) != card_id]
                _persist_api_cards(settings, kind, cards)
                st.success(f"{title} apagada.")
                st.rerun()
    if st.button("Adicionar nova API", type="primary", width="stretch", key=f"add_{kind}_api_card"):
        identifier_key = "account_id" if is_instagram else "page_id"
        cards.append({"id": f"{kind}-api-{uuid.uuid4().hex[:10]}", "label": f"Conta {len(cards) + 1}", identifier_key: "", "access_token": ""})
        _persist_api_cards(settings, kind, cards)
        st.success(f"Novo card {title} criado.")
        st.rerun()


def _instagram_profiles() -> list[dict[str, Any]]:
    records = read_json("channels.json", [])
    profiles: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        platform = _clean(item.get("platform")).lower()
        network = _clean(item.get("social_network")).lower()
        url = _clean(item.get("url")).lower()
        if platform == "instagram" or network == "instagram" or "instagram.com/" in url:
            profiles.append(item)
    return profiles


def _characters(settings: Mapping[str, Any]) -> tuple[list[dict[str, Any]], Any | None]:
    try:
        repository = get_repository(settings)
        items = [item for item in repository.list_influencers() if _clean(item.get("id")) != STANDALONE_CONTENT_INFLUENCER_ID]
        return items, repository
    except (InfluencerBackendError, Exception):
        return [], None


def _canonical_instagram_metrics(profile: Mapping[str, Any]) -> dict[str, int | None]:
    return {
        "post_count": _profile_metric(profile, "post_count", "posts", "media_count"),
        "subscriber_count": _profile_metric(profile, "subscriber_count", "followers_count", "follower_count", "followers", "edge_followed_by"),
        "following_count": _profile_metric(profile, "following_count", "following", "follows", "followingCount", "edge_follow"),
    }


def _canonical_instagram_profile(data: Mapping[str, Any], existing: Mapping[str, Any] | None = None) -> dict[str, Any]:
    current = dict(existing or {})
    incoming = dict(data)
    merged = {**current, **incoming}
    for field, value in _canonical_instagram_metrics(incoming).items():
        if value is not None:
            merged[field] = value
        elif field not in merged or merged.get(field) in (None, ""):
            merged[field] = _canonical_instagram_metrics(current).get(field)
    bio = _profile_bio(incoming) or _profile_bio(current)
    if bio:
        merged["bio"] = bio
    raw_bio = _clean(incoming.get("bio_raw")) or _clean(incoming.get("biography")) or _clean(current.get("bio_raw"))
    if raw_bio:
        merged["bio_raw"] = raw_bio
    country = _profile_country(incoming) or _profile_country(current)
    if country:
        merged["country"] = country
    return merged


def _save_public_profile(data: Mapping[str, Any], *, country: str, language: str, character_id: str = "", instagram_model_type: str = "", instagram_model_id: str = "") -> dict[str, Any]:
    canonical = _canonical_instagram_profile(data)
    name = _clean(canonical.get("name")) or _clean(canonical.get("username")) or "Conta Instagram"
    url = _clean(canonical.get("url"))
    metrics = _canonical_instagram_metrics(canonical)
    bio = _profile_bio(canonical)
    metadata = {
        **canonical,
        "platform": "instagram",
        "social_network": "Instagram",
        "name": name,
        "url": url,
        "handle": _clean(canonical.get("handle")) or _clean(canonical.get("username")),
        "bio": bio,
        "bio_raw": _clean(data.get("bio_raw")) or _clean(canonical.get("bio_raw")) or bio,
        "country": _normalise_country(country) or _profile_country(canonical),
        "language": language.strip(),
        "post_count": metrics["post_count"],
        "subscriber_count": metrics["subscriber_count"],
        "following_count": metrics["following_count"],
        "character_id": character_id.strip(),
        "instagram_model_type": instagram_model_type.strip(),
        "instagram_model_id": instagram_model_id.strip(),
        "active": True,
        "metrics_source": "instagram_public_page",
    }
    return create_channel(name, url, metadata)


def _merge_instagram_refresh(existing: Mapping[str, Any], refreshed: Mapping[str, Any]) -> dict[str, Any]:
    merged = _canonical_instagram_profile(refreshed, existing)
    merged["id"] = existing.get("id") or refreshed.get("id")
    merged["platform"] = "instagram"
    merged["social_network"] = "Instagram"
    return merged


def _refresh_instagram_profile(profile: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    source = _clean(profile.get("url")) or _clean(profile.get("handle"))
    result = fetch_public_instagram_profile(source)
    if not result.ok:
        return False, result.message, {}
    return True, result.message, _merge_instagram_refresh(profile, result.data)


def _load_instagram_posts(profile: Mapping[str, Any], limit: int = 10) -> tuple[bool, str, list[dict[str, Any]]]:
    source = _clean(profile.get("url")) or _clean(profile.get("handle"))
    result = fetch_public_instagram_posts(source, limit=limit)
    posts = result.data.get("posts", []) if isinstance(result.data, dict) else []
    return result.ok, result.message, posts


def _render_instagram_card(profile: dict[str, Any], characters: list[dict[str, Any]], settings: Mapping[str, Any]) -> None:
    profile_id = _clean(profile.get("id"))
    edit_key = f"edit_instagram_profile_{profile_id}"
    with st.container(border=True):
        header_cols = st.columns([0.7, 3.1, 1.25, 1.25, 1.25, 1.65])
        with header_cols[0]:
            if _clean(profile.get("avatar_url")):
                st.image(profile["avatar_url"], width=64)
            else:
                st.markdown("### IG")
        with header_cols[1]:
            st.write(f"**{_clean(profile.get('name')) or 'Sem nome'}**")
            st.caption(f"{_clean(profile.get('handle')) or _clean(profile.get('url')) or 'sem handler'}")
            _render_instagram_bio(_profile_bio(profile))
            country = _profile_country(profile)
            st.caption(f"{_country_display(country) if country else 'País não definido'} · {_clean(profile.get('language')) or 'Idioma não definido'}")
        with header_cols[2]:
            st.metric("posts", _metric(_profile_metric(profile, "post_count", "posts", "media_count")))
        with header_cols[3]:
            followers = _profile_metric(profile, "subscriber_count", "followers_count", "follower_count")
            followers = followers if followers is not None else _profile_metric(profile, "followers", "edge_followed_by")
            st.metric("Seguidores", _metric(followers))
        with header_cols[4]:
            following = _profile_metric(profile, "following_count", "following", "follows")
            following = following if following is not None else _profile_metric(profile, "followingCount", "edge_follow")
            st.metric("seguindo", _metric(following))
        with header_cols[5]:
            refresh_col, edit_col = st.columns(2)
            with refresh_col:
                if st.button("↻", help="Actualizar posts, seguidores e seguindo", key=f"refresh_instagram_{profile_id}"):
                    refreshed_ok, refreshed_message, refreshed = _refresh_instagram_profile(profile)
                    if refreshed_ok:
                        current_posts = _stored_instagram_posts(profile)
                        posts_ok, _, refreshed_posts = _load_instagram_posts(refreshed, limit=max(10, len(current_posts)))
                        if posts_ok:
                            _persist_instagram_posts(profile, refreshed_posts)
                        updated = update_channel(profile_id, {**refreshed, "id": profile_id, "country": _profile_country(refreshed) or _profile_country(profile), "language": profile.get("language", ""), "character_id": profile.get("character_id", "")})
                        if updated is None:
                            st.error("A conta Instagram já não existe no armazenamento local.")
                            return
                        st.success("Métricas Instagram actualizadas.")
                        st.rerun()
                    st.warning(refreshed_message)
            with edit_col:
                if st.button("Editar", key=f"edit_instagram_button_{profile_id}", width="stretch"):
                    for field in ("name", "handle", "bio", "country", "language", "posts", "followers", "following"):
                        st.session_state.pop(f"instagram_edit_{field}_{profile_id}", None)
                    st.session_state[edit_key] = True
                    st.rerun()
            if st.button("Apagar", key=f"delete_instagram_button_{profile_id}", width="stretch"):
                st.session_state[f"confirm_delete_instagram_{profile_id}"] = True
                st.rerun()
            url = _clean(profile.get("url"))
            if url:
                st.link_button("Abrir Instagram", url, width="stretch")

        if st.session_state.get(f"confirm_delete_instagram_{profile_id}"):
            st.warning("Apagar este card remove o cadastro da conta Instagram, mas não os ficheiros associados.")
            confirm_cols = st.columns(2)
            with confirm_cols[0]:
                if st.button("Confirmar apagar", type="primary", key=f"confirm_delete_instagram_button_{profile_id}", width="stretch"):
                    delete_channel(profile_id)
                    st.session_state.pop(f"confirm_delete_instagram_{profile_id}", None)
                    st.success("Conta Instagram apagada.")
                    st.rerun()
            with confirm_cols[1]:
                if st.button("Cancelar", key=f"cancel_delete_instagram_button_{profile_id}", width="stretch"):
                    st.session_state.pop(f"confirm_delete_instagram_{profile_id}", None)
                    st.rerun()

        if st.session_state.get(edit_key):
            with st.form(f"edit_instagram_profile_form_{profile_id}"):
                edit_cols = st.columns(2)
                with edit_cols[0]:
                    name = st.text_input("Nome", value=_clean(profile.get("name")), key=f"instagram_edit_name_{profile_id}")
                    handle = st.text_input("handler", value=_clean(profile.get("handle")), key=f"instagram_edit_handle_{profile_id}")
                    bio = st.text_area("Bio", value=_profile_bio(profile), key=f"instagram_edit_bio_{profile_id}")
                    country = st.selectbox("País", _country_options(), index=_country_index(_profile_country(profile)), format_func=_country_label, key=f"instagram_edit_country_{profile_id}")
                    language = st.selectbox("Idioma", list(LANGUAGE_CODES), index=_language_index(profile.get("language")), format_func=language_label, key=f"instagram_edit_language_{profile_id}")
                with edit_cols[1]:
                    posts = st.number_input("posts", min_value=0, value=_metric_input(_profile_metric(profile, "post_count", "posts", "media_count")), placeholder="Não encontrado", key=f"instagram_edit_posts_{profile_id}")
                    followers = st.number_input("Seguidores", min_value=0, value=_metric_input(_profile_metric(profile, "subscriber_count", "followers_count", "follower_count", "followers", "edge_followed_by")), placeholder="Não encontrado", key=f"instagram_edit_followers_{profile_id}")
                    following = st.number_input("seguindo", min_value=0, value=_metric_input(_profile_metric(profile, "following_count", "following", "follows", "followingCount", "edge_follow")), placeholder="Não encontrado", key=f"instagram_edit_following_{profile_id}")
                save_edit = st.form_submit_button("Guardar alterações", type="primary", width="stretch")
            if save_edit:
                update_channel(profile_id, {"name": name.strip(), "handle": handle.strip(), "bio": bio, "bio_raw": bio, "country": _normalise_country(country), "language": language, "post_count": _metric_input(posts), "subscriber_count": _metric_input(followers), "following_count": _metric_input(following)})
                st.session_state.pop(edit_key, None)
                st.success("Conta Instagram actualizada.")
                st.rerun()
        else:
            block_cols = st.columns(4, gap="small")
            with block_cols[0]:
                st.markdown(f"**Nome**\n\n{_clean(profile.get('name')) or '—'}")
            with block_cols[1]:
                st.markdown(f"**handler**\n\n{_clean(profile.get('handle')) or '—'}")
            with block_cols[2]:
                country = _profile_country(profile)
                st.markdown(f"**País**\n\n{_country_display(country) if country else '—'}")
            with block_cols[3]:
                st.markdown(f"**Idioma**\n\n{_clean(profile.get('language')) or '—'}")

        character_options = [""] + [_clean(item.get("id")) for item in characters if _clean(item.get("id"))]
        character_labels = {"": "Sem personagem associado"} | {_clean(item.get("id")): _clean(item.get("name")) or _clean(item.get("id")) for item in characters}
        current_character = _clean(profile.get("character_id"))
        selected_character = st.selectbox("Personagem", character_options, index=character_options.index(current_character) if current_character in character_options else 0, format_func=lambda value: character_labels.get(value, value), key=f"instagram_character_{profile_id}")
        if st.button("Atrelar Personagem", key=f"attach_instagram_character_{profile_id}", width="stretch"):
            update_channel(profile_id, {"character_id": selected_character})
            st.success("Personagem associado à conta Instagram.")
            st.rerun()
        model_type, model_id = _render_instagram_model_selector(profile, settings, key_prefix=f"instagram_{profile_id}")
        if st.button("Guardar modelo atrelado", type="primary", key=f"save_instagram_model_{profile_id}", width="stretch"):
            update_channel(profile_id, {"instagram_model_type": model_type, "instagram_model_id": model_id})
            st.success(f"{model_type} atrelado à conta Instagram.")
            st.rerun()
        resolved_model = resolve_instagram_model(profile, settings)
        st.caption(f"Modelo da Automação Instagram: {resolved_model['type']} · {resolved_model['label']}")
        _render_instagram_posts(profile)


def render_social_networks(settings: dict[str, Any]) -> None:
    st.title("Contas Instagram")
    st.caption("Cadastre contas Instagram através de pesquisa pública e associe cada conta a um Personagem de AI Influencers.")
    search_tab, accounts_tab = st.tabs(["Pesquisa pública Instagram", "Contas Instagram"])
    with search_tab:
        st.caption("A pesquisa consulta apenas a página pública do Instagram. API Key não é necessária para cadastrar o perfil.")
        source = st.text_input("URL pública ou @handler Instagram", placeholder="https://www.instagram.com/conta/ ou @conta", key="social_instagram_source")
        search_cols = st.columns(2)
        with search_cols[0]:
            search_clicked = st.button("Pesquisar conta pública", type="primary", width="stretch", key="social_instagram_search")
        with search_cols[1]:
            if st.button("Limpar pesquisa", width="stretch", key="social_instagram_clear"):
                for key in ("social_instagram_result", "social_instagram_ok", "social_instagram_message"):
                    st.session_state.pop(key, None)
                st.rerun()
        if search_clicked:
            result = fetch_public_instagram_profile(source)
            result_data = dict(result.data) if isinstance(result.data, dict) else {}
            st.session_state["social_instagram_result"] = result_data
            st.session_state["social_instagram_ok"] = result.ok
            st.session_state["social_instagram_message"] = result.message
        if st.session_state.get("social_instagram_message"):
            (st.success if st.session_state.get("social_instagram_ok") else st.warning)(st.session_state["social_instagram_message"])
        data = st.session_state.get("social_instagram_result", {}) if st.session_state.get("social_instagram_ok") else {}
        if data:
            characters, _ = _characters(settings)
            result_widget_id = _instagram_profile_storage_id(data)
            with st.container(border=True):
                st.subheader("Conta Instagram encontrada")
                preview_cols = st.columns([0.8, 2.2, 1.2, 1.2, 1.2])
                with preview_cols[0]:
                    if _clean(data.get("avatar_url")):
                        st.image(data["avatar_url"], width=72)
                with preview_cols[1]:
                    st.write(f"**{_clean(data.get('name')) or _clean(data.get('username'))}**")
                    st.caption(_clean(data.get("handle")))
                    _render_instagram_bio(_profile_bio(data))
                with preview_cols[2]:
                    st.metric("posts", _metric(_profile_metric(data, "post_count", "posts", "media_count")))
                with preview_cols[3]:
                    st.metric("Seguidores", _metric(_profile_metric(data, "subscriber_count", "followers_count", "follower_count", "followers", "edge_followed_by")))
                with preview_cols[4]:
                    st.metric("seguindo", _metric(_profile_metric(data, "following_count", "following", "follows", "followingCount", "edge_follow")))
                with st.form(f"social_instagram_save_public_profile_{result_widget_id}"):
                    form_cols = st.columns(2)
                    with form_cols[0]:
                        name = st.text_input("Nome", value=_clean(data.get("name")), key=f"social_instagram_result_name_{result_widget_id}")
                        bio = st.text_area("Bio", value=_profile_bio(data), key=f"social_instagram_result_bio_{result_widget_id}")
                        country = st.selectbox("País", _country_options(), index=_country_index(_profile_country(data)), format_func=_country_label, key=f"social_instagram_result_country_{result_widget_id}")
                        language = st.selectbox("Idioma", list(LANGUAGE_CODES), index=_language_index(data.get("language")), format_func=language_label, key=f"social_instagram_result_language_{result_widget_id}")
                    with form_cols[1]:
                        posts = st.number_input("posts", min_value=0, value=_metric_input(_profile_metric(data, "post_count", "posts", "media_count")), placeholder="Não encontrado", key=f"social_instagram_result_posts_{result_widget_id}")
                        followers = st.number_input("Seguidores", min_value=0, value=_metric_input(_profile_metric(data, "subscriber_count", "followers_count", "follower_count", "followers", "edge_followed_by")), placeholder="Não encontrado", key=f"social_instagram_result_followers_{result_widget_id}")
                        following = st.number_input("seguindo", min_value=0, value=_metric_input(_profile_metric(data, "following_count", "following", "follows", "followingCount", "edge_follow")), placeholder="Não encontrado", key=f"social_instagram_result_following_{result_widget_id}")
                    character_options = [""] + [_clean(item.get("id")) for item in characters if _clean(item.get("id"))]
                    character_labels = {"": "Sem personagem associado"} | {_clean(item.get("id")): _clean(item.get("name")) or _clean(item.get("id")) for item in characters}
                    selected_character = st.selectbox("Personagem", character_options, format_func=lambda value: character_labels.get(value, value), key=f"social_instagram_result_character_{result_widget_id}")
                    selected_model_type, selected_model_id = _render_instagram_model_selector(data, settings, key_prefix=f"social_instagram_result_{result_widget_id}")
                    save_profile = st.form_submit_button("Cadastrar conta Instagram", type="primary", width="stretch")
                if save_profile:
                    profile_data = dict(data)
                    profile_data.update({"name": name, "bio": bio, "bio_raw": bio, "post_count": _metric_input(posts), "subscriber_count": _metric_input(followers), "following_count": _metric_input(following)})
                    profile_data["country"] = _normalise_country(country)
                    _save_public_profile(profile_data, country=profile_data["country"], language=language, character_id=selected_character, instagram_model_type=selected_model_type, instagram_model_id=selected_model_id)
                    st.success("Conta Instagram cadastrada em Contas Instagram.")
                    for key in ("social_instagram_result", "social_instagram_ok", "social_instagram_message"):
                        st.session_state.pop(key, None)
                    st.rerun()
    with accounts_tab:
        profiles = _instagram_profiles()
        if not profiles:
            st.info("Ainda não existem contas Instagram cadastradas. Use a pesquisa pública para adicionar a primeira conta.")
        characters, _ = _characters(settings)
        for profile in profiles:
            _render_instagram_card(profile, characters, settings)


def render_instagram_automation(settings: dict[str, Any]) -> None:
    """Show the Instagram automation model selected on each account."""
    st.title("Automação Instagram")
    st.caption("Cada geração de conteúdo Instagram usa o modelo atrelado à conta: Prompt-Masters Tiktok, Facebook Blueprint ou Personagens Influencer/UGC.")
    profiles = _instagram_profiles()
    if not profiles:
        st.info("Ainda não existem contas Instagram cadastradas. Pode continuar a trabalhar e associar um modelo quando cadastrar uma conta.")
        return
    for profile in profiles:
        profile_id = _clean(profile.get("id"))
        resolved = resolve_instagram_model(profile, settings)
        with st.container(border=True):
            st.subheader(_clean(profile.get("name")) or "Conta Instagram")
            st.caption(_clean(profile.get("handle")) or _clean(profile.get("url")) or "sem handle")
            st.write(f"**Modelo usado na geração:** {resolved['type']}")
            st.write(f"**Blueprint/modelo atrelado:** {resolved['label']}")
            if not resolved["id"]:
                st.info("Nenhum modelo está atrelado. Pode continuar a trabalhar; escolha um modelo em Contas Instagram quando quiser gerar conteúdo para esta conta.")
            else:
                st.success("A automação utilizará este modelo para gerar o conteúdo da conta.")
