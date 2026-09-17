"""Ordered YouTube upload routing for Thunderbolt.

The route is intentionally deterministic:
1. Composio, when the configured upload tool is available.
2. Official YouTube API, up to five successful sends per Google account/day.
3. Internal browser-session upload, when the account document is complete.
4. Postiz, when configured with an API key and integration ID.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable

from integrations.platforms import IntegrationResult, YouTubeAdapter
from integrations.postiz import PostizAdapter
from integrations.session_info_health import check_account_session_info_health, emit_session_info_health_alerts
from integrations.youtube_direct_credentials import document_status
from integrations.youtube_direct_upload import YouTubeDirectUploader
from integrations.youtube_session_manager import renew_account_session
from integrations.composio_upload import ComposioUploadError, _client, execute_upload, resolve_tool_slug
from integrations.composio_account_resolver import AccountDiscoveryError, candidate_message, discover_connected_account
from hermes_ui.storage import read_json, update_json, write_json
from hermes_ui.languages import language_locale

OFFICIAL_DAILY_LIMIT = 5
QUOTA_FILENAME = "official_upload_quota.json"
COMPOSIO_VIDEO_FILE_FIELD = "videoFilePath"
COMPOSIO_OPERATION_OPTIONS = {
    "upload_video": "Upload Video",
    "update_video": "Update video",
    "upload_tiktok_video": "Upload TikTok Video",
    "upload_instagram_media": "Upload Instagram vídeo/Reel/foto",
}
COMPOSIO_PRIVACY_VALUES = {"listed", "unlisted"}
COMPOSIO_CATEGORY_RANGE = range(1, 101)


def _attempt_record(name: str, result: IntegrationResult, *, skipped: bool = False) -> dict[str, Any]:
    return {
        "route": name,
        "status": "skipped" if skipped else ("success" if result.ok else "failed"),
        "message": result.message,
        "data": result.data,
    }


def resolve_youtube_account(settings: dict[str, Any], channel: dict[str, Any] | None) -> dict[str, Any] | None:
    """Resolve the configured Google account without relying only on the channel ID.

    Older channel records may retain the account e-mail while the account ID is
    missing or stale. Prefer an exact ID match, then use a case-insensitive
    e-mail match, and finally accept a sole configured account only when the
    channel has no contradictory account reference.
    """
    if not isinstance(channel, dict):
        return None
    accounts = [item for item in settings.get("youtube_batch_accounts", []) if isinstance(item, dict) and item.get("id")]
    if not accounts:
        return None
    account_id = str(channel.get("google_account_id") or "").strip()
    if account_id:
        match = next((item for item in accounts if str(item.get("id") or "").strip() == account_id), None)
        if match is not None:
            return match
    account_email = str(channel.get("google_account_email") or "").strip().casefold()
    if account_email:
        match = next((item for item in accounts if str(item.get("email") or "").strip().casefold() == account_email), None)
        if match is not None:
            return match
    if not account_id and not account_email and len(accounts) == 1:
        return accounts[0]
    return None


def _quota_key(channel: dict[str, Any], account: dict[str, Any] | None) -> str:
    if account and account.get("id"):
        return f"account:{account['id']}"
    if channel.get("google_account_id"):
        return f"account:{channel['google_account_id']}"
    if channel.get("google_account_email"):
        return f"account-email:{str(channel['google_account_email']).strip().casefold()}"
    return f"channel:{channel.get('id', 'unknown')}"


def official_upload_count(channel: dict[str, Any], account: dict[str, Any] | None, *, today: str | None = None) -> int:
    today = today or date.today().isoformat()
    state = read_json(QUOTA_FILENAME, {})
    if not isinstance(state, dict):
        return 0
    entry = state.get(_quota_key(channel, account), {})
    if not isinstance(entry, dict) or entry.get("date") != today:
        return 0
    try:
        return max(0, int(entry.get("count", 0)))
    except (TypeError, ValueError):
        return 0


def record_official_upload(channel: dict[str, Any], account: dict[str, Any] | None, *, today: str | None = None) -> int:
    today = today or date.today().isoformat()
    state = read_json(QUOTA_FILENAME, {})
    if not isinstance(state, dict):
        state = {}
    key = _quota_key(channel, account)
    current = official_upload_count(channel, account, today=today)
    state[key] = {"date": today, "count": current + 1}
    write_json(QUOTA_FILENAME, state)
    return current + 1


def _result_with_attempts(result: IntegrationResult, attempts: list[dict[str, Any]], route: str) -> IntegrationResult:
    data = dict(result.data or {})
    data["route"] = route
    data["attempts"] = attempts
    return IntegrationResult(result.ok, result.message, data)


def _channel_composio_data(channel: dict[str, Any]) -> dict[str, Any]:
    nested = channel.get("composio")
    if isinstance(nested, dict):
        return nested
    legacy_id = str(channel.get("composio_connected_account_id") or "").strip()
    return {"connected_account_id": legacy_id} if legacy_id.startswith("ca_") else {}


def _persist_channel_composio(channel: dict[str, Any], data: dict[str, Any]) -> None:
    channel_id = str(channel.get("id") or "").strip()
    if not channel_id:
        channel.update({"composio": dict(data), "composio_connected_account_id": data.get("connected_account_id", "")})
        return

    def mutate(channels: Any) -> None:
        if not isinstance(channels, list):
            return
        for item in channels:
            if isinstance(item, dict) and str(item.get("id") or "") == channel_id:
                item["composio"] = dict(data)
                item["composio_connected_account_id"] = data.get("connected_account_id", "")
                break

    update_json("channels.json", [], mutate)
    channel["composio"] = dict(data)
    channel["composio_connected_account_id"] = data.get("connected_account_id", "")


def _resolve_channel_composio(settings: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
    cached = _channel_composio_data(channel)
    if cached.get("connected_account_id") and cached.get("user_id"):
        return cached
    client = _client(str(settings.get("composio_api_key") or ""))
    try:
        resolved = discover_connected_account(
            client,
            str(channel.get("name") or channel.get("title") or ""),
            channel_id_youtube=str(channel.get("youtube_channel_id") or channel.get("youtube_id") or ""),
        )
    except AccountDiscoveryError as exc:
        raise ComposioUploadError(f"Não foi possível associar o canal ao Composio. {exc} {candidate_message(exc.candidates)}") from exc
    if not resolved:
        raise ComposioUploadError(
            f"Não foi possível encontrar a conta conectada para o canal '{channel.get('name') or 'seleccionado'}'. "
            f"{candidate_message([])} Remova o registo se o canal já não existir no YouTube."
        )
    _persist_channel_composio(channel, resolved)
    return resolved


def upload_with_default_route(
    settings: dict[str, Any],
    *,
    storage_root: Path,
    channel: dict[str, Any],
    account: dict[str, Any] | None,
    video_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "22",
    language: str = "pt-BR",
    privacy_status: str = "unlisted",
    thumbnail_path: str = "",
    captions_path: str = "",
    official_uploader: Callable[..., IntegrationResult] | None = None,
    direct_uploader: Callable[..., IntegrationResult] | None = None,
    postiz_publisher: Callable[..., IntegrationResult] | None = None,
    composio_publisher: Callable[..., IntegrationResult] | None = None,
) -> IntegrationResult:
    attempts: list[dict[str, Any]] = []
    account = account or resolve_youtube_account(settings, channel)
    composio_enabled = bool(settings.get("composio_enabled", False)) and bool(settings.get("composio_auto_upload", True))
    composio_ready = composio_enabled and bool(settings.get("composio_api_key"))
    if composio_enabled and not composio_ready:
        composio_result = IntegrationResult(False, "Composio está activo, mas falta API key ou slug da ferramenta de upload.", {})
        attempts.append(_attempt_record("Composio", composio_result, skipped=True))
    elif composio_ready:
        composio_publisher = composio_publisher or _composio_upload
        try:
            composio_result = composio_publisher(
                settings,
                channel=channel,
                video_path=video_path,
                category_id=category_id,
                language=language or channel.get("language") or "pt-BR",
                privacy_status=privacy_status or "unlisted",
                title=title,
                description=description,
                tags=tags or [],
                thumbnail_path=thumbnail_path,
                captions_path=captions_path,
            )
        except Exception as exc:
            composio_result = IntegrationResult(False, f"Composio falhou: {type(exc).__name__}: {exc}", {})
        attempts.append(_attempt_record("Composio", composio_result))
        if composio_result.ok:
            return _result_with_attempts(composio_result, attempts, "Composio")

    quota_count = official_upload_count(channel, account)
    if quota_count >= OFFICIAL_DAILY_LIMIT:
        quota_result = IntegrationResult(False, f"Limite local de {OFFICIAL_DAILY_LIMIT} envios oficiais por conta Google atingido hoje; a tentar o próximo método.", {"count": quota_count, "limit": OFFICIAL_DAILY_LIMIT})
        attempts.append(_attempt_record("API Oficial", quota_result, skipped=True))
    else:
        official_uploader = official_uploader or YouTubeAdapter(settings).upload_video
        try:
            official_result = official_uploader(
                video_path,
                title=title,
                description=description,
                tags=tags or [],
                category_id=category_id,
                language=language,
                privacy_status=privacy_status,
                thumbnail_path=thumbnail_path,
                captions_path=captions_path,
                account=account,
            )
        except Exception as exc:  # Keep fallback actionable and deterministic.
            official_result = IntegrationResult(False, f"API Oficial falhou: {exc}", {})
        attempts.append(_attempt_record("API Oficial", official_result))
        if official_result.ok:
            used = record_official_upload(channel, account)
            data = dict(official_result.data or {})
            data["official_daily_count"] = used
            data["official_daily_limit"] = OFFICIAL_DAILY_LIMIT
            data["route"] = "API Oficial"
            data["attempts"] = attempts
            return IntegrationResult(True, official_result.message, data)

    direct_ready = False
    if account:
        try:
            renewal_warning = ""
            if bool(account.get("auto_renew_before_upload", settings.get("auto_renew_before_upload", False))):
                current_health = check_account_session_info_health(storage_root, account, settings)
                if current_health.status in {"expiring", "expired"}:
                    renewal = renew_account_session(storage_root, account, settings, wait_seconds=10)
                    if not renewal.ok:
                        renewal_warning = f"Renovação automática não concluída ({renewal.status}); o upload pode falhar."
                        attempts.append({"route": "Renovação sessionInfo", "status": "failed", "message": renewal_warning, "data": {"status": renewal.status}})
                    else:
                        attempts.append({"route": "Renovação sessionInfo", "status": "success", "message": renewal.message, "data": {"status": renewal.status}})
            status = document_status(storage_root, account, channel, settings, [channel])
            health = check_account_session_info_health(storage_root, account, settings)
            emit_session_info_health_alerts([health])
            direct_ready = bool(status.get("ready")) and health.status != "expired"
            if health.status == "expired":
                direct_result = IntegrationResult(
                    False,
                    f"Upload directo indisponível: {health.message}",
                    {"missing": ["sessionInfo"], "session_info_health": health.as_dict(), "renewal_warning": renewal_warning},
                )
            elif not direct_ready:
                missing = list(status.get("missing_cookies", []))
                if not status.get("has_session_info"):
                    missing.append("sessionInfo")
                if not status.get("has_innertube_api_key"):
                    missing.append("INNERTUBE_API_KEY")
                if not status.get("has_delegated_session_id"):
                    missing.append("DELEGATED_SESSION_ID")
                direct_result = IntegrationResult(False, f"Upload directo indisponível: {', '.join(missing)}. {renewal_warning}".strip(), {"missing": missing, "renewal_warning": renewal_warning})
            else:
                direct_result = None
        except Exception as exc:
            direct_result = IntegrationResult(False, f"Não foi possível validar o documento do Upload directo: {exc}", {})
    else:
        direct_result = IntegrationResult(False, "Upload directo indisponível: o canal não tem uma conta Google associada.", {})
    if direct_ready:
        direct_uploader = direct_uploader or YouTubeDirectUploader(settings, channel, account=account, storage_root=storage_root).upload
        try:
            direct_result = direct_uploader(video_path, title=title, description=description, visibility=privacy_status)
        except Exception as exc:
            direct_result = IntegrationResult(False, f"Upload directo falhou: {exc}", {})
    attempts.append(_attempt_record("Upload directo", direct_result))
    if direct_result.ok:
        return _result_with_attempts(direct_result, attempts, "Upload directo")

    postiz = PostizAdapter(settings)
    if not bool(settings.get("postiz_enabled", False)):
        postiz_result = IntegrationResult(False, "Postiz está desactivado em Configuração API > API Keys > Serviços e modelos.", {})
        attempts.append(_attempt_record("Postiz", postiz_result, skipped=True))
    else:
        postiz_publisher = postiz_publisher or postiz.publish_video
        try:
            postiz_result = postiz_publisher(
                video_path,
                integration_id=str(settings.get("postiz_integration_id", "") or ""),
                title=title,
                description=description,
                visibility=privacy_status,
                tags=tags or [],
                thumbnail_path=thumbnail_path,
            )
        except Exception as exc:
            postiz_result = IntegrationResult(False, f"Postiz falhou: {exc}", {})
        attempts.append(_attempt_record("Postiz", postiz_result))
        if postiz_result.ok:
            return _result_with_attempts(postiz_result, attempts, "Postiz")

    return IntegrationResult(False, "Nenhum método de envio conseguiu publicar o vídeo.", {"attempts": attempts, "route": "none"})


def _composio_upload(settings: dict[str, Any], *, channel: dict[str, Any], **kwargs: Any) -> IntegrationResult:
    configured_slug = str(channel.get("composio_tool_slug") or channel.get("upload_operation") or "upload_video").strip()
    composio_data = _channel_composio_data(channel)
    resolved_user_id = str(composio_data.get("user_id") or settings.get("composio_user_id") or "").strip()
    resolved_account_id = str(composio_data.get("connected_account_id") or "").strip()
    if (channel.get("id") or channel.get("name")) and not (resolved_account_id and composio_data.get("user_id")):
        try:
            composio_data = _resolve_channel_composio(settings, channel)
            resolved_user_id = str(composio_data.get("user_id") or "").strip()
            resolved_account_id = str(composio_data.get("connected_account_id") or "").strip()
        except ComposioUploadError as exc:
            return IntegrationResult(False, str(exc), {"status": "account_discovery_failed"})
    try:
        if configured_slug.casefold() == "upload_video" and (channel.get("platform", "youtube") or "youtube").casefold() == "youtube":
            slug = "YOUTUBE_UPLOAD_VIDEO"
        else:
            slug = resolve_tool_slug(
                str(settings.get("composio_api_key") or ""),
                resolved_user_id,
                configured_slug,
                str(channel.get("composio_toolkit") or ""),
            )
    except ComposioUploadError as exc:
        return IntegrationResult(False, str(exc), {"status": "tool_resolution_failed", "configured_slug": configured_slug})
    normalized_slug = slug.upper().replace("-", "_")
    connected_account_tool = normalized_slug in {"UPLOAD_VIDEO", "UPDATE_VIDEO", "UPLOAD_TIKTOK_VIDEO", "UPLOAD_INSTAGRAM_MEDIA"}
    youtube_upload_tool = normalized_slug in {"UPLOAD_VIDEO", "YOUTUBE_UPLOAD_VIDEO", "YOUTUBE_MULTIPART_UPLOAD_VIDEO"} or ("YOUTUBE" in normalized_slug and "UPLOAD" in normalized_slug and normalized_slug != "YOUTUBE_UPLOAD")
    channel_id = str(
        channel.get("youtube_channel_id")
        or channel.get("youtube_id")
        or channel.get("google_channel_id")
        or channel.get("channel_id")
        or ""
    ).strip()
    if not channel_id:
        import re
        match = re.search(r"/channel/(UC[\w-]+)", str(channel.get("url") or ""))
        channel_id = match.group(1) if match else ""
    channel_field = str(settings.get("composio_channel_field") or "channel_id").strip()
    if not connected_account_tool and not youtube_upload_tool and not channel_id:
        return IntegrationResult(False, "Composio não foi executado: o canal da tarefa não tem um YouTube channel ID sincronizado.", {"missing": ["youtube_channel_id"]})
    if not connected_account_tool and not youtube_upload_tool and not channel_field:
        return IntegrationResult(False, "Composio não foi executado: configure o campo de canal da ferramenta.", {"missing": ["composio_channel_field"]})
    # O path técnico nunca vem da configuração editável: é injectado pelo backend.
    file_field = COMPOSIO_VIDEO_FILE_FIELD
    try:
        arguments = str(settings.get("composio_arguments_json") or "{}").strip() or "{}"
        import json
        parsed_arguments = json.loads(arguments)
        if not isinstance(parsed_arguments, dict):
            return IntegrationResult(False, "Composio não foi executado: os argumentos JSON devem ser um objecto.", {})
        for field in ("title", "description", "tags"):
            if field in kwargs and kwargs[field] is not None:
                parsed_arguments[field] = kwargs[field]
        privacy_value = "unlisted"
        category_value = 22
        locked_values = {
            **({channel_field: channel_id} if channel_field and not youtube_upload_tool else {}),
            "privacyStatus": privacy_value,
            "categoryId": str(category_value),
            "defaultLanguage": language_locale(kwargs.get("language") or channel.get("language") or "en"),
        }
        if "category_id" in parsed_arguments and str(parsed_arguments["category_id"]) not in {"", str(category_value)}:
            return IntegrationResult(False, "Composio bloqueado: o campo `category_id` tem um valor diferente do upload oficial (22).", {"field": "category_id", "expected": str(category_value)})
        for field, expected in locked_values.items():
            if not field:
                return IntegrationResult(False, "Composio não foi executado: existe um campo obrigatório vazio na configuração.", {})
            configured_value = parsed_arguments.get(field)
            if configured_value not in (None, "", expected):
                if field == channel_field:
                    return IntegrationResult(False, f"Composio bloqueado: o campo `{field}` aponta para outro canal.", {"field": field, "expected": expected})
                return IntegrationResult(False, f"Composio bloqueado: o campo `{field}` tem um valor diferente do upload oficial ({expected}).", {"field": field, "expected": expected})
            parsed_arguments[field] = expected
        execute_args = (
            str(settings.get("composio_api_key") or ""), resolved_user_id, slug,
            str(kwargs.get("video_path") or ""), file_field,
            json.dumps(parsed_arguments, ensure_ascii=False),
        )
        result = execute_upload(*execute_args, **({"connected_account_id": resolved_account_id} if resolved_account_id else {}))
        error_text = str(result.get("error") or "")
        invalid_account = any(marker in error_text.casefold() for marker in ("connected account not found", "connected_account_not_found", "account not found", "conta conectada") )
        if invalid_account and resolved_account_id and (channel.get("id") or channel.get("name")):
            _persist_channel_composio(channel, {})
            refreshed = _resolve_channel_composio(settings, channel)
            result = execute_upload(
                str(settings.get("composio_api_key") or ""),
                str(refreshed.get("user_id") or ""), slug, str(kwargs.get("video_path") or ""), file_field,
                json.dumps(parsed_arguments, ensure_ascii=False), connected_account_id=str(refreshed.get("connected_account_id") or ""),
            )
    except ComposioUploadError as exc:
        return IntegrationResult(False, str(exc), {})
    return IntegrationResult(
        bool(result.get("successful")),
        str(result.get("error") or "Upload via Composio concluído."),
        {"composio_data": result.get("data") or {}, "log_id": result.get("log_id") or "", "tool_slug": result.get("tool_slug") or slug, "configured_tool_slug": configured_slug, "connected_account_id": result.get("connected_account_id") or "", "connected_account_alias": result.get("connected_account_alias") or ""},
    )
