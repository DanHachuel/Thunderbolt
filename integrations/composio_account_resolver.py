"""Resolve real Composio connected accounts for YouTube channels."""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class AccountDiscoveryError(RuntimeError):
    """Actionable discovery failure, including candidates when available."""

    def __init__(self, message: str, *, candidates: list[dict[str, Any]] | None = None, retryable: bool = False):
        super().__init__(message)
        self.candidates = candidates or []
        self.retryable = retryable


@dataclass
class DiscoveryResult:
    connected_account_id: str
    user_id: str
    channel_id_youtube: str
    channel_title: str
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "connected_account_id": self.connected_account_id,
            "user_id": self.user_id,
            "channel_id_youtube": self.channel_id_youtube,
            "channel_title": self.channel_title,
            "candidates": self.candidates,
        }


def normalize_channel_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^\w\s-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"[\s_-]+", " ", text).strip().casefold()


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    for method in ("model_dump", "to_dict", "dict"):
        converter = getattr(value, method, None)
        if callable(converter):
            try:
                return _safe_value(converter())
            except Exception:
                pass
    attributes = getattr(value, "__dict__", None)
    return _safe_value(attributes) if isinstance(attributes, dict) else str(value)


def _items(response: Any) -> list[Any]:
    raw = _safe_value(response)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("items", "connected_accounts", "connections"):
            if isinstance(raw.get(key), list):
                return raw[key]
        return _items(raw.get("data")) if raw.get("data") is not None else []
    return []


def _field(item: Any, *names: str) -> Any:
    raw = _safe_value(item)
    if not isinstance(raw, dict):
        return None
    lowered = {str(key).casefold().replace("_", ""): value for key, value in raw.items()}
    for name in names:
        value = lowered.get(name.casefold().replace("_", ""))
        if value not in (None, ""):
            return value
    return None


def _retryable(exc: Exception) -> bool:
    text = str(exc).casefold()
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if str(status) in {"400", "401", "403", "404"} or any(token in text for token in ("forbidden", "unauthoriz", "scope", "not found", "does not exist")):
        return False
    return str(status) == "429" or any(token in text for token in ("timeout", "temporar", "connection", "rate limit", "too many requests", "429"))


def _sleep_for(exc: Exception, attempt: int) -> float:
    retry_after = getattr(exc, "retry_after", None) or getattr(exc, "headers", {}).get("Retry-After") if hasattr(getattr(exc, "headers", None), "get") else None
    try:
        return min(30.0, max(0.0, float(retry_after))) if retry_after is not None else min(8.0, 0.25 * (2 ** (attempt - 1)))
    except (TypeError, ValueError):
        return min(8.0, 0.25 * (2 ** (attempt - 1)))


def _execute_list_channels(client: Any, account: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            return client.tools.execute(
                slug="YOUTUBE_LIST_CHANNELS",
                connected_account_id=_field(account, "id", "connection_id", "connectionId", "connected_account_id"),
                user_id=_field(account, "user_id", "userId"),
                arguments={"part": "snippet", "mine": True},
                dangerously_skip_version_check=True,
            )
        except Exception as exc:
            last_error = exc
            if not _retryable(exc) or attempt == 3:
                raise
            logger.warning("Composio YouTube discovery retry=%s reason=%s", attempt, type(exc).__name__)
            time.sleep(_sleep_for(exc, attempt))
    raise last_error or RuntimeError("discovery failed")


def discover_connected_account(client: Any, channel_name: str, *, channel_id_youtube: str = "", toolkit: str = "youtube") -> dict[str, Any] | None:
    """Return one match, or None when absent; ambiguity raises with candidates."""
    target_name = normalize_channel_name(channel_name)
    target_id = str(channel_id_youtube or "").strip()
    accounts = _items(client.connected_accounts.list(toolkit_slugs=[toolkit]))
    candidates: list[dict[str, Any]] = []
    matches: list[DiscoveryResult] = []
    for account in accounts:
        account_id = str(_field(account, "id", "connection_id", "connectionId", "connected_account_id") or "").strip()
        user_id = str(_field(account, "user_id", "userId") or "").strip()
        if not account_id or not user_id:
            continue
        try:
            result = _safe_value(_execute_list_channels(client, account))
            data = result.get("data", result) if isinstance(result, dict) else {}
            items = data.get("items", []) if isinstance(data, dict) else []
            for channel in items if isinstance(items, list) else []:
                channel_id = str(_field(channel, "id") or "").strip()
                title = str(_field(channel, "title") or _field(_field(channel, "snippet") or {}, "title") or "").strip()
                if not channel_id or not title:
                    continue
                candidate = {"connected_account_id": account_id, "user_id": user_id, "channel_id_youtube": channel_id, "channel_title": title}
                candidates.append(candidate)
                if (target_id and channel_id == target_id) or (not target_id and target_name and normalize_channel_name(title) == target_name):
                    matches.append(DiscoveryResult(**candidate))
        except Exception as exc:
            logger.warning("Composio YouTube account check failed account=%s error=%s", account_id, type(exc).__name__)
            continue
    unique = {(item.connected_account_id, item.channel_id_youtube): item for item in matches}
    if len(unique) > 1:
        options = [item.as_dict() for item in unique.values()]
        raise AccountDiscoveryError("Foram encontradas várias contas YouTube compatíveis; seleccione uma conta técnica.", candidates=options)
    if len(unique) == 1:
        resolved = next(iter(unique.values())).as_dict()
        logger.info("Canal %s: connected_account_id=%s resolvido via descoberta automática", channel_name, resolved["connected_account_id"])
        return resolved
    return None


def candidate_message(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "Nenhuma conta/canal YouTube correspondente foi encontrado. O canal pode ter sido removido ou desconectado do Composio."
    labels = [f"{item.get('channel_title') or 'sem título'} ({item.get('channel_id_youtube') or 'sem channel ID'})" for item in candidates]
    return "Canais candidatos encontrados: " + ", ".join(labels)
