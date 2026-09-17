"""Composio Platform adapter for user-selected video upload tools."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any


class ComposioUploadError(ValueError):
    """Safe, user-facing validation or integration error."""


class YouTubeUploadScopeMissingError(ComposioUploadError):
    """The connected YouTube account cannot publish videos."""


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
LOGGER = logging.getLogger(__name__)


COMPOSIO_OPERATION_SEARCH = {
    "upload_video": {"query": "Multipart Upload Video", "toolkit": "YOUTUBE"},
    "update_video": {"query": "Update Video", "toolkit": "YOUTUBE"},
    "upload_tiktok_video": {"query": "Upload Video", "toolkit": "TIKTOK"},
    "upload_instagram_media": {"query": "Upload Video Reel Photo", "toolkit": "INSTAGRAM"},
}

# O alias identifica a conta dentro do contexto do utilizador e toolkit. O
# cache evita uma chamada de listagem a cada upload durante a execução do
# processo, sem persistir credenciais ou dados entre reinícios.
_CONNECTED_ACCOUNT_ID_CACHE: dict[tuple[str, str, str], str] = {}


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    for method in ("model_dump", "to_dict", "dict"):
        converter = getattr(value, method, None)
        if callable(converter):
            try:
                return _safe_value(converter())
            except Exception:
                pass
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return {str(key): _safe_value(item) for key, item in attributes.items()}
    return str(value)


def _tool_item(tool: Any) -> dict[str, Any]:
    raw = _safe_value(tool)
    if isinstance(raw, dict) and isinstance(raw.get("function"), dict):
        function = raw["function"]
        return {
            "slug": str(function.get("name") or raw.get("name") or ""),
            "name": str(function.get("name") or raw.get("name") or ""),
            "description": str(function.get("description") or raw.get("description") or ""),
            "toolkit": str(raw.get("toolkit") or ""),
            "schema": function.get("parameters") or {},
        }
    if isinstance(raw, dict):
        toolkit = raw.get("toolkit")
        if isinstance(toolkit, dict):
            toolkit = toolkit.get("slug") or toolkit.get("name") or ""
        return {
            "slug": str(raw.get("slug") or raw.get("name") or ""),
            "name": str(raw.get("name") or raw.get("slug") or ""),
            "description": str(raw.get("description") or ""),
            "toolkit": str(toolkit or ""),
            "schema": raw.get("input_parameters") or raw.get("parameters") or {},
        }
    return {"slug": "", "name": "", "description": "", "toolkit": "", "schema": {}}


def _account_field(item: dict[str, Any], *names: str) -> Any:
    """Read account fields across SDK 0.21 response/model naming styles."""
    lowered = {str(key).casefold().replace("_", ""): value for key, value in item.items()}
    for name in names:
        value = lowered.get(name.casefold().replace("_", ""))
        if value not in (None, ""):
            return value
    return None


def _response(result: Any) -> dict[str, Any]:
    raw = _safe_value(result)
    if not isinstance(raw, dict):
        raw = {"data": raw}
    data = raw.get("data")
    if not isinstance(data, dict):
        data = {"value": data} if data is not None else {}
    error = raw.get("error") or raw.get("message") or data.get("error") or data.get("message")
    explicit_success = raw.get("successful")
    if explicit_success is None:
        explicit_success = raw.get("success")
    successful = bool(explicit_success) if explicit_success is not None else not bool(error)
    return {
        "successful": successful and not bool(error),
        "data": data,
        "error": str(error) if error else "",
        "log_id": str(raw.get("log_id") or raw.get("request_id") or ""),
    }


def _require_api_key(api_key: str) -> str:
    value = str(api_key or "").strip()
    if len(value) < 10 or value.lower() in {"placeholder", "your_composio_api_key"}:
        raise ComposioUploadError("Configure uma API key válida do Composio em Configuração API > API Keys Upload > Composio.")
    return value


def _require_user_id(user_id: str) -> str:
    value = str(user_id or "").strip()
    if not value:
        raise ComposioUploadError("Indique um Composio user ID estável antes de continuar.")
    return value


def _client(api_key: str, *, upload_dir: Path | None = None):
    try:
        from composio import Composio
    except ImportError as exc:
        raise ComposioUploadError("A SDK Python composio não está instalada. Execute a instalação do Thunderbolt novamente.") from exc
    kwargs: dict[str, Any] = {"api_key": _require_api_key(api_key), "allow_tracking": False}
    if upload_dir is not None:
        kwargs.update({
            "dangerously_allow_auto_upload_download_files": True,
            "file_upload_dirs": [str(upload_dir.resolve())],
        })
    return Composio(**kwargs)


def _connected_account_id(client: Any, user_id: str, toolkit: str, selector: str) -> str:
    """Resolve a connected-account ID from an ID, alias, or sole active account."""
    value = str(selector or "").strip()
    # Technical IDs are authoritative. Do not reinterpret or list them using
    # the configured application user; Composio accounts belong to acc.user_id.
    if value.startswith("ca_"):
        return value
    normalized_user_id = _require_user_id(user_id)
    normalized_toolkit = str(toolkit or "").strip().casefold()
    cache_key = (normalized_user_id, normalized_toolkit, value.casefold())
    if value:
        cached_id = _CONNECTED_ACCOUNT_ID_CACHE.get(cache_key)
        if cached_id:
            return cached_id
    try:
        response = client.connected_accounts.list(
            user_ids=[normalized_user_id],
            statuses=["ACTIVE"],
            toolkit_slugs=[str(toolkit).strip().lower()] if toolkit else None,
        )
        raw = _safe_value(response)

        # Composio SDK versions expose this response as a list, a paginated
        # dict, or a model whose payload is nested under ``data``.  Walk those
        # shapes explicitly; otherwise an alias is incorrectly passed through
        # as the connected-account ID and Composio reports it as not found.
        def collection(payload: Any) -> Any:
            if isinstance(payload, list):
                return payload
            if not isinstance(payload, dict):
                return []
            for key in ("items", "connected_accounts", "connections"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    return candidate
            data = payload.get("data")
            if data is not None and data is not payload:
                nested = collection(data)
                if nested:
                    return nested
                if isinstance(data, list):
                    return data
            return []

        items = collection(raw)
        if not isinstance(items, list):
            items = []
        matching_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            toolkit_value = _account_field(item, "toolkit", "toolkit_slug", "toolkitSlug")
            if isinstance(toolkit_value, dict):
                toolkit_value = _account_field(toolkit_value, "slug", "name", "id")
            # The request is already filtered by toolkit_slugs. Some SDK
            # response models omit toolkit metadata, so absence is not a
            # reason to discard an otherwise valid connected account.
            if str(toolkit or "").strip() and toolkit_value and toolkit.casefold() not in str(toolkit_value).casefold():
                continue
            matching_items.append(item)
        if value:
            wanted = value.casefold()
            matched_items = []
            for item in matching_items:
                candidates = [
                    _account_field(item, "id", "nanoid", "connection_id", "connectionId", "connected_account_id", "connectedAccountId"),
                    _account_field(item, "alias", "name", "label"),
                ]
                if any(str(candidate or "").strip().casefold() == wanted for candidate in candidates):
                    matched_items.append(item)
            if len(matched_items) > 1:
                raise ComposioUploadError(
                    f"A connected account `{value}` aparece em múltiplas contas do toolkit {toolkit}. "
                    "Use o ID técnico imutável para escolher uma só conta."
                )
            if matched_items:
                item = matched_items[0]
                technical_id = str(
                    _account_field(item, "id", "nanoid", "connection_id", "connectionId", "connected_account_id", "connectedAccountId")
                    or ""
                ).strip()
                if technical_id:
                    if value:
                        _CONNECTED_ACCOUNT_ID_CACHE[cache_key] = technical_id
                    return technical_id
            available = [str(item.get("alias") or item.get("name") or item.get("id") or "").strip() for item in matching_items]
            available = [item for item in available if item]
            suffix = f" Contas activas: {', '.join(available)}." if available else ""
            raise ComposioUploadError(
                f"A connected account `{value}` não foi encontrada para o toolkit {toolkit or 'seleccionado'}.{suffix}"
            )
        if len(matching_items) == 1:
            item = matching_items[0]
            technical_id = str(_account_field(item, "id", "nanoid", "connection_id", "connectionId", "connected_account_id", "connectedAccountId") or "").strip()
            if technical_id:
                if value:
                    _CONNECTED_ACCOUNT_ID_CACHE[cache_key] = technical_id
                return technical_id
    except ComposioUploadError:
        raise
    except Exception as exc:
        raise ComposioUploadError(
            f"Não foi possível resolver a connected account `{value or 'activa'}` para {toolkit}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    raise ComposioUploadError(
        f"A connected account `{value or 'activa'}` não foi encontrada para o toolkit {toolkit or 'seleccionado'}."
    )


def _connected_account_details(client: Any, account_id: str) -> dict[str, Any]:
    response = client.connected_accounts.get(account_id)
    raw = _safe_value(response)
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, dict):
            return data
        return raw
    return {}


def _flatten_scope_values(value: Any) -> set[str]:
    scopes: set[str] = set()
    if isinstance(value, str):
        scopes.update(item.strip() for item in value.replace(",", " ").split() if item.strip())
    elif isinstance(value, list):
        for item in value:
            scopes.update(_flatten_scope_values(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in {"scope", "scopes", "granted_scopes", "grantedscopes"}:
                scopes.update(_flatten_scope_values(item))
            elif isinstance(item, (dict, list)):
                scopes.update(_flatten_scope_values(item))
    return scopes


def ensure_youtube_upload_scope(client: Any, account_id: str, alias: str = "") -> None:
    """Fail before upload when the connected account is read-only."""
    try:
        details = _connected_account_details(client, account_id)
    except Exception as exc:
        raise ComposioUploadError(
            f"Não foi possível verificar os scopes da connected account `{alias or account_id}` "
            f"(ID técnico `{account_id}`): {type(exc).__name__}: {exc}"
        ) from exc
    scopes = _flatten_scope_values(details)
    if YOUTUBE_UPLOAD_SCOPE not in scopes:
        label = alias or account_id
        raise YouTubeUploadScopeMissingError(
            f"A conta YouTube `{label}` (ID técnico `{account_id}`) não tem o scope de upload "
            f"`{YOUTUBE_UPLOAD_SCOPE}`. Reautorize a conta com o comando "
            f"`python scripts/reauth_youtube.py --account {label}` e conceda a permissão no navegador."
        )


def discover_tools(api_key: str, user_id: str, query: str, toolkit: str = "") -> list[dict[str, Any]]:
    client = _client(api_key)
    try:
        tools = client.tools.get(
            _require_user_id(user_id),
            search=(query or "upload a video file").strip(),
            toolkits=[toolkit.strip()] if toolkit.strip() else None,
            limit=10,
        )
        return [item for item in (_tool_item(tool) for tool in tools) if item.get("slug")]
    except ComposioUploadError:
        raise
    except Exception as exc:
        raise ComposioUploadError(f"Não foi possível descobrir ferramentas Composio: {type(exc).__name__}: {exc}") from exc


def resolve_tool_slug(api_key: str, user_id: str, configured_slug: str, toolkit: str = "") -> str:
    """Resolve a Thunderbolt operation alias to a real Composio tool slug."""
    slug = str(configured_slug or "").strip()
    operation = COMPOSIO_OPERATION_SEARCH.get(slug)
    if operation is None:
        return slug
    search_toolkit = str(operation["toolkit"] or toolkit or "").strip()
    tools = discover_tools(api_key, user_id, str(operation["query"]), search_toolkit)
    if not tools:
        raise ComposioUploadError(
            f"Não foi encontrada uma ferramenta Composio para `{slug}`. "
            f"Ligue o toolkit {search_toolkit or 'correspondente'} e use Descobrir ferramentas."
        )

    def score(item: dict[str, Any]) -> tuple[int, str]:
        candidate = str(item.get("slug") or "").strip()
        normalized = candidate.upper().replace("-", "_")
        if slug == "upload_video":
            priority = {
                "YOUTUBE_MULTIPART_UPLOAD_VIDEO": 0,
                "YOUTUBE_UPLOAD_VIDEO": 1,
                "YOUTUBE_UPLOAD": 2,
            }.get(normalized, 3)
        elif slug == "update_video":
            priority = 0 if normalized == "YOUTUBE_UPDATE_VIDEO" else 1
        else:
            priority = 0 if "VIDEO" in normalized and "UPLOAD" in normalized else 1
        return priority, candidate

    return min((item for item in tools if item.get("slug")), key=score)["slug"]


def authorize_toolkit(api_key: str, user_id: str, toolkit: str) -> dict[str, Any]:
    toolkit = str(toolkit or "").strip()
    if not toolkit:
        raise ComposioUploadError("Seleccione uma ferramenta descoberta para saber qual toolkit deve ser autorizado.")
    client = _client(api_key)
    try:
        request = client.create(user_id=_require_user_id(user_id)).authorize(toolkit)
        return {"connected_account_id": str(getattr(request, "id", "") or ""), "redirect_url": str(getattr(request, "redirect_url", "") or "")}
    except ComposioUploadError:
        raise
    except Exception as exc:
        raise ComposioUploadError(f"Não foi possível criar o Connect Link do Composio: {type(exc).__name__}: {exc}") from exc


def parse_arguments(arguments_json: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        raise ComposioUploadError(f"Os argumentos da ferramenta não são JSON válido: {exc.msg}.") from exc
    if not isinstance(parsed, dict):
        raise ComposioUploadError("Os argumentos da ferramenta devem ser um objecto JSON.")
    return parsed


def execute_upload(api_key: str, user_id: str, slug: str, video_path: str, file_field: str, arguments_json: str = "", connected_account_id: str = "") -> dict[str, Any]:
    path = Path(str(video_path or "").strip()).expanduser()
    slug = str(slug or "").strip()
    file_field = str(file_field or "").strip()
    if not path.is_file():
        raise ComposioUploadError("O ficheiro de vídeo seleccionado não existe ou não é um ficheiro.")
    if path.stat().st_size <= 0:
        raise ComposioUploadError("O ficheiro de vídeo seleccionado está vazio.")
    if not slug:
        raise ComposioUploadError("Seleccione ou indique o slug de uma ferramenta Composio.")
    if not file_field:
        raise ComposioUploadError("Indique o campo de argumentos que recebe o ficheiro.")
    arguments = parse_arguments(arguments_json)
    if file_field in arguments and arguments[file_field] not in (None, "", str(path)):
        raise ComposioUploadError(f"O campo `{file_field}` já contém um valor. Remova-o antes de injectar o vídeo.")
    client = _client(api_key, upload_dir=path.parent)
    try:
        local_video_path = str(path.resolve())
        arguments[file_field] = {
            "name": path.name,
            "mimetype": "video/mp4",
            "s3key": local_video_path,
        }
        LOGGER.info(
            "Composio upload file argument: value=%r type=%s size=%d bytes auto_upload_download_files=True",
            arguments[file_field],
            type(arguments[file_field]).__name__,
            path.stat().st_size,
        )
        execute_kwargs: dict[str, Any] = {
            "arguments": arguments,
            "user_id": _require_user_id(user_id),
            "version": "latest",
            "dangerously_skip_version_check": True,
        }
        selected_account = _connected_account_id(client, user_id, "youtube", connected_account_id)
        if not selected_account:
            raise ComposioUploadError(
                f"Nenhuma conta YouTube activa está ligada ao Composio user ID `{_require_user_id(user_id)}`. "
                "Use `Autorizar toolkit no Composio` ou configure o Connected account ID correcto."
            )
        execute_kwargs["connected_account_id"] = selected_account
        normalized_slug = slug.upper().replace("-", "_")
        if "YOUTUBE" in normalized_slug and "UPLOAD" in normalized_slug:
            ensure_youtube_upload_scope(client, selected_account, connected_account_id)
        result = client.tools.execute(slug, **execute_kwargs)
        raw_result = _safe_value(result)
        LOGGER.info("Composio response complete (including returned s3key when available): %s", raw_result)
        response = _response(result)
        LOGGER.info("Composio response normalised: %s", response)
        if not response["successful"] and not response["error"]:
            response["error"] = f"A ferramenta `{slug}` devolveu uma resposta sem sucesso."
        response["tool_slug"] = slug
        response["connected_account_id"] = selected_account
        response["connected_account_alias"] = connected_account_id
        return response
    except ComposioUploadError:
        raise
    except Exception as exc:
        safe_message = str(exc).replace(str(api_key), "[REDACTED]")
        raise ComposioUploadError(f"A ferramenta Composio falhou: {type(exc).__name__}: {safe_message}") from exc


def test_configuration(api_key: str, user_id: str) -> dict[str, Any]:
    tools = discover_tools(api_key, user_id, "upload a video file")
    return {"successful": True, "data": {"tools": tools}, "error": "", "log_id": ""}
