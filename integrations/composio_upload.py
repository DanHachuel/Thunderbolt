"""Composio Platform adapter for user-selected video upload tools."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ComposioUploadError(ValueError):
    """Safe, user-facing validation or integration error."""


COMPOSIO_OPERATION_SEARCH = {
    "upload_video": {"query": "Upload Video", "toolkit": "YOUTUBE"},
    "update_video": {"query": "Update Video", "toolkit": "YOUTUBE"},
    "upload_tiktok_video": {"query": "Upload Video", "toolkit": "TIKTOK"},
    "upload_instagram_media": {"query": "Upload Video Reel Photo", "toolkit": "INSTAGRAM"},
}


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
    try:
        response = client.connected_accounts.list(user_ids=[_require_user_id(user_id)], statuses=["ACTIVE"])
        raw = _safe_value(response)
        if isinstance(raw, dict):
            # Composio SDK versions expose the list either directly or under
            # ``data``; accept both shapes so aliases are never sent as IDs.
            items = raw.get("items")
            if items is None:
                data = raw.get("data")
                items = data.get("items", data) if isinstance(data, dict) else data
            if items is None:
                items = raw.get("connected_accounts", [])
        else:
            items = raw
        if not isinstance(items, list):
            items = []
        matching_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            toolkit_value = item.get("toolkit")
            if isinstance(toolkit_value, dict):
                toolkit_value = toolkit_value.get("slug") or toolkit_value.get("name")
            if str(toolkit or "").strip() and toolkit.casefold() not in str(toolkit_value or "").casefold():
                continue
            matching_items.append(item)
        if value:
            wanted = value.casefold()
            for item in matching_items:
                candidates = [item.get("id"), item.get("nanoid"), item.get("alias"), item.get("name")]
                if any(str(candidate or "").strip().casefold() == wanted for candidate in candidates):
                    technical_id = str(item.get("id") or item.get("nanoid") or "").strip()
                    if technical_id:
                        return technical_id
            available = [str(item.get("alias") or item.get("name") or item.get("id") or "").strip() for item in matching_items]
            available = [item for item in available if item]
            suffix = f" Contas activas: {', '.join(available)}." if available else ""
            raise ComposioUploadError(
                f"A connected account `{value}` não foi encontrada para o toolkit {toolkit or 'seleccionado'}.{suffix}"
            )
        if len(matching_items) == 1:
            item = matching_items[0]
            return str(item.get("id") or item.get("nanoid") or "").strip()
    except ComposioUploadError:
        raise
    except Exception:
        # Preserve the original selector so Composio returns its actionable error.
        return value
    return value


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
                "YOUTUBE_UPLOAD_VIDEO": 0,
                "YOUTUBE_MULTIPART_UPLOAD_VIDEO": 1,
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
    arguments[file_field] = str(path.resolve())
    client = _client(api_key, upload_dir=path.parent)
    try:
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
        result = client.tools.execute(slug, **execute_kwargs)
        response = _response(result)
        if not response["successful"] and not response["error"]:
            response["error"] = f"A ferramenta `{slug}` devolveu uma resposta sem sucesso."
        response["tool_slug"] = slug
        return response
    except ComposioUploadError:
        raise
    except Exception as exc:
        safe_message = str(exc).replace(str(api_key), "[REDACTED]")
        raise ComposioUploadError(f"A ferramenta Composio falhou: {type(exc).__name__}: {safe_message}") from exc


def test_configuration(api_key: str, user_id: str) -> dict[str, Any]:
    tools = discover_tools(api_key, user_id, "upload a video file")
    return {"successful": True, "data": {"tools": tools}, "error": "", "log_id": ""}
