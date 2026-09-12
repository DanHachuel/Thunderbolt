"""Routing, retry and rate limiting shared by text, image and video providers.

The module deliberately stores only redacted provider metadata. API keys are used
only in memory to derive a one-way bucket fingerprint and are never persisted.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

import requests

from .llm_providers import (
    LLM_ACTIVE_CARD_KEY,
    ensure_llm_provider_cards,
    normalize_llm_card,
    provider_definition,
)
from .storage import STORAGE, atomic_write, ensure_storage
from app.modules.token_optimizer import compress_text


POOL_LLM = "llm_text"
POOL_IMAGE = "image"
POOL_VIDEO = "video"
POOLS = (POOL_LLM, POOL_IMAGE, POOL_VIDEO)
RATE_LIMIT_FILENAME = "llm_rate_limit.json"
ATTEMPTS_FILENAME = "provider_attempts.json"
COOLDOWNS_FILENAME = "provider_cooldowns.json"
DEFAULT_RPM_LIMIT = 40
DEFAULT_RPM_WINDOW_SECONDS = 60
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_COOLDOWN_SECONDS = 120
_LOCK_WAIT_SECONDS = 5.0
_STALE_LOCK_SECONDS = 45.0


class ProviderRoutingError(RuntimeError):
    """Raised when no provider in a pool can complete a request."""

    def __init__(self, message: str, *, attempts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


class ProviderCallError(RuntimeError):
    """A provider response or transport failure with a safe retry category."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        category: str = "unknown",
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class RoutedResponse:
    card: dict[str, Any]
    payload: dict[str, Any]
    attempts: tuple[dict[str, Any], ...]


def _now() -> float:
    return time.time()


def _iso(timestamp: float | None = None) -> str:
    return datetime.fromtimestamp(timestamp or _now(), timezone.utc).isoformat()


def _safe_host(value: Any) -> str:
    try:
        return urlparse(str(value or "")).netloc or ""
    except ValueError:
        return ""


def _redacted_card_metadata(card: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(card.get("id") or ""),
        "provider": str(card.get("provider") or ""),
        "model": str(card.get("model") or ""),
        "base_url_host": _safe_host(card.get("base_url")),
    }


def is_nvidia_nim_card(card: Mapping[str, Any]) -> bool:
    """Identify NIM by provider or endpoint, not by the generic OpenAI label alone."""
    provider = str(card.get("provider") or "").strip().lower()
    host = _safe_host(card.get("base_url")).lower()
    return provider in {"nvidia", "nvidia_nim"} or host == "integrate.api.nvidia.com"


def _card_fingerprint(card: Mapping[str, Any]) -> str:
    secret = str(card.get("api_key") or "").strip()
    material = "|".join(
        (
            str(card.get("provider") or "").strip().lower(),
            str(card.get("id") or "").strip(),
            str(card.get("base_url") or "").strip().lower(),
            str(card.get("model") or "").strip(),
            secret,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


@contextmanager
def _exclusive_lock(path: Path):
    """Small cross-process lock for the local JSON rate-limit state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = _now() + _LOCK_WAIT_SECONDS
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if _now() - path.stat().st_mtime > _STALE_LOCK_SECONDS:
                    path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if _now() >= deadline:
                raise ProviderRoutingError("Não foi possível reservar o estado de routing local.")
            time.sleep(0.02)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
    finally:
        os.close(descriptor)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _load_state(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save_state(path: Path, value: Any) -> None:
    """Persist provider routing state without exposing a partial JSON file."""
    atomic_write(path, value)


def nvidia_rpm_enabled(settings: Mapping[str, Any]) -> bool:
    return bool(settings.get("llm_rpm_limit_enabled", False))


def nvidia_rpm_limit(settings: Mapping[str, Any]) -> int:
    try:
        return max(1, min(1000, int(settings.get("llm_rpm_limit", DEFAULT_RPM_LIMIT))))
    except (TypeError, ValueError):
        return DEFAULT_RPM_LIMIT


def nvidia_rpm_window(settings: Mapping[str, Any]) -> float:
    try:
        return max(1.0, min(3600.0, float(settings.get("llm_rpm_window_seconds", DEFAULT_RPM_WINDOW_SECONDS))))
    except (TypeError, ValueError):
        return float(DEFAULT_RPM_WINDOW_SECONDS)


def should_apply_nvidia_rpm(settings: Mapping[str, Any], card: Mapping[str, Any]) -> bool:
    return nvidia_rpm_enabled(settings) and is_nvidia_nim_card(card)


def acquire_nvidia_rpm_slot(
    settings: Mapping[str, Any],
    card: Mapping[str, Any],
    *,
    sleep: bool = True,
    now: Callable[[], float] = _now,
) -> float:
    """Reserve one request slot; return seconds waited (or required when sleep=False)."""
    if not should_apply_nvidia_rpm(settings, card):
        return 0.0
    ensure_storage()
    path = STORAGE / "state" / RATE_LIMIT_FILENAME
    lock = path.with_suffix(path.suffix + ".lock")
    limit = nvidia_rpm_limit(settings)
    window = nvidia_rpm_window(settings)
    started = now()
    while True:
        with _exclusive_lock(lock):
            state = _load_state(path, {})
            if not isinstance(state, dict):
                state = {}
            bucket_id = _card_fingerprint(card)
            timestamps = state.get(bucket_id, [])
            if not isinstance(timestamps, list):
                timestamps = []
            current = now()
            timestamps = [float(item) for item in timestamps if current - float(item) < window]
            if len(timestamps) < limit:
                timestamps.append(current)
                state[bucket_id] = timestamps
                _save_state(path, state)
                return max(0.0, current - started)
            wait_for = max(0.0, timestamps[0] + window - current)
        if not sleep:
            return wait_for
        if wait_for > 0:
            time.sleep(wait_for)


def _status_category(status_code: int) -> tuple[str, bool]:
    if status_code in {402, 429}:
        return "quota", True
    if status_code in {408, 425} or status_code >= 500:
        return "transient", True
    if status_code in {401, 403}:
        return "credential", False
    if status_code == 404:
        return "endpoint_or_model", False
    if 400 <= status_code < 500:
        return "payload", False
    return "unknown", False


def _retry_after(response: Any) -> float | None:
    value = str(getattr(response, "headers", {}).get("Retry-After") or "").strip()
    try:
        return max(0.0, min(3600.0, float(value))) if value else None
    except (TypeError, ValueError):
        return None


def _detail(response: Any) -> str:
    text = str(getattr(response, "text", "") or "").strip().replace("\n", " ")
    return text[:240] or "sem detalhe devolvido pelo provider"


def classify_request_exception(exc: BaseException) -> ProviderCallError:
    return ProviderCallError(
        f"Falha de transporte no provider: {str(exc)[:220]}",
        category="transient",
        retryable=True,
    )


def classify_response(response: Any) -> None:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if 200 <= status_code < 300:
        return
    category, retryable = _status_category(status_code)
    raise ProviderCallError(
        f"Provider devolveu HTTP {status_code}: {_detail(response)}",
        status_code=status_code,
        category=category,
        retryable=retryable,
        retry_after=_retry_after(response),
    )


def enabled_cards(settings: Mapping[str, Any], pool: str) -> list[dict[str, Any]]:
    """Return cards in deterministic priority order; media pools keep active-card preference."""
    if pool == POOL_LLM:
        migrated, _ = ensure_llm_provider_cards(settings)
        raw_cards = migrated.get("llm_provider_cards", [])
        cards = [normalize_llm_card(item, index) for index, item in enumerate(raw_cards)] if isinstance(raw_cards, list) else []
        enabled = [
            (index, card)
            for index, card in enumerate(cards)
            if bool(card.get("enabled", True))
            and not bool(card.get("telegram_llm", False))
            and not provider_definition(card.get("provider")).excluded_from_normal_pool
        ]
        enabled.sort(key=lambda pair: (int(pair[1].get("priority", 1)), pair[0]))
        return [card for _index, card in enabled]
    raw_cards = settings.get("media_provider_cards", [])
    cards = [dict(item) for item in raw_cards if isinstance(item, Mapping)] if isinstance(raw_cards, list) else []
    active_key = "media_image_active_card_id" if pool == POOL_IMAGE else "media_video_active_card_id"
    active_id = str(settings.get(active_key) or "")
    enabled = [card for card in cards if bool(card.get("enabled", True))]
    if active_id:
        enabled.sort(key=lambda item: 0 if str(item.get("id")) == active_id else 1)
    return enabled


def _attempt_record(pool: str, card: Mapping[str, Any], *, started: float, finished: float, status_code: int | None, category: str, error: str = "", waited: float = 0.0) -> dict[str, Any]:
    return {
        "created_at": _iso(finished),
        "pool": pool,
        **_redacted_card_metadata(card),
        "status_code": status_code,
        "category": category,
        "error": str(error or "")[:240],
        "duration_ms": int(max(0.0, finished - started) * 1000),
        "rate_limit_wait_ms": int(max(0.0, waited) * 1000),
    }


def record_provider_attempt(record: Mapping[str, Any]) -> None:
    ensure_storage()
    path = STORAGE / "state" / ATTEMPTS_FILENAME
    lock = path.with_suffix(path.suffix + ".lock")
    with _exclusive_lock(lock):
        entries = _load_state(path, [])
        if not isinstance(entries, list):
            entries = []
        entries.append(dict(record))
        _save_state(path, entries[-2000:])


def provider_cooldown_remaining(card: Mapping[str, Any], *, now: Callable[[], float] = _now) -> float:
    ensure_storage()
    path = STORAGE / "state" / COOLDOWNS_FILENAME
    state = _load_state(path, {})
    if not isinstance(state, dict):
        return 0.0
    try:
        return max(0.0, float(state.get(_card_fingerprint(card), 0.0)) - now())
    except (TypeError, ValueError):
        return 0.0


def set_provider_cooldown(card: Mapping[str, Any], seconds: float) -> None:
    ensure_storage()
    path = STORAGE / "state" / COOLDOWNS_FILENAME
    lock = path.with_suffix(path.suffix + ".lock")
    with _exclusive_lock(lock):
        state = _load_state(path, {})
        if not isinstance(state, dict):
            state = {}
        state[_card_fingerprint(card)] = _now() + max(0.0, min(3600.0, float(seconds)))
        _save_state(path, state)


def clear_provider_cooldown(card: Mapping[str, Any]) -> None:
    ensure_storage()
    path = STORAGE / "state" / COOLDOWNS_FILENAME
    lock = path.with_suffix(path.suffix + ".lock")
    with _exclusive_lock(lock):
        state = _load_state(path, {})
        if not isinstance(state, dict):
            return
        state.pop(_card_fingerprint(card), None)
        _save_state(path, state)


def route_json_request(
    settings: Mapping[str, Any],
    *,
    pool: str,
    cards: Iterable[Mapping[str, Any]] | None,
    request: Callable[[dict[str, Any]], Any],
    max_attempts: int | None = None,
    cooldown_seconds: float | None = None,
) -> RoutedResponse:
    """Execute a JSON request over eligible cards with classified priority failover."""
    if pool not in POOLS:
        raise ProviderRoutingError(f"Pool de providers inválido: {pool}")
    candidates = [dict(item) for item in (cards if cards is not None else enabled_cards(settings, pool))]
    if pool == POOL_LLM:
        candidates = [card for card in candidates if not bool(card.get("telegram_llm", False))]
        candidates = [
            card
            for _index, card in sorted(
                enumerate(candidates),
                key=lambda pair: (int(pair[1].get("priority", pair[0] + 1)), pair[0]),
            )
        ]
    if not candidates:
        raise ProviderRoutingError(f"Não existem providers activos no pool {pool}.")
    try:
        if pool == POOL_LLM and max_attempts is None:
            maximum = len(candidates)
        else:
            configured_max_attempts = max_attempts if max_attempts is not None else settings.get("provider_max_attempts")
            maximum = max(1, min(len(candidates), int(configured_max_attempts or DEFAULT_MAX_ATTEMPTS)))
    except (TypeError, ValueError):
        maximum = len(candidates) if pool == POOL_LLM else min(len(candidates), DEFAULT_MAX_ATTEMPTS)
    cooldown = float(cooldown_seconds if cooldown_seconds is not None else settings.get("provider_cooldown_seconds", DEFAULT_COOLDOWN_SECONDS))
    attempts: list[dict[str, Any]] = []
    for card in candidates[:maximum]:
        started = _now()
        waited = 0.0
        remaining = provider_cooldown_remaining(card)
        if remaining > 0:
            record = _attempt_record(pool, card, started=started, finished=_now(), status_code=None, category="cooldown", error=f"provider em cooldown por mais de {int(remaining)}s")
            attempts.append(record)
            record_provider_attempt(record)
            continue
        try:
            if pool == POOL_LLM:
                waited = acquire_nvidia_rpm_slot(settings, card)
            response = request(card)
            if isinstance(response, Mapping):
                status_code = response.get("status_code")
            else:
                status_code = getattr(response, "status_code", None)
            classify_response(response)
            payload = response if isinstance(response, dict) else response.json()
            if not isinstance(payload, dict):
                raise ProviderCallError("Provider devolveu um payload JSON inválido.", category="payload", retryable=False)
            record = _attempt_record(pool, card, started=started, finished=_now(), status_code=int(status_code or 200), category="success", waited=waited)
            attempts.append(record)
            record_provider_attempt(record)
            clear_provider_cooldown(card)
            return RoutedResponse(card=card, payload=payload, attempts=tuple(attempts))
        except ProviderCallError as exc:
            record = _attempt_record(pool, card, started=started, finished=_now(), status_code=exc.status_code, category=exc.category, error=str(exc), waited=waited)
            attempts.append(record)
            record_provider_attempt(record)
            if exc.retryable or exc.category in {"credential", "endpoint_or_model"}:
                set_provider_cooldown(card, exc.retry_after or cooldown or DEFAULT_COOLDOWN_SECONDS)
            if not exc.retryable and pool != POOL_LLM:
                raise ProviderRoutingError(str(exc), attempts=attempts) from exc
            if exc.retry_after:
                time.sleep(min(3600.0, exc.retry_after))
            elif exc.retryable and cooldown > 0 and len(attempts) < maximum:
                time.sleep(min(cooldown, 5.0))
        except requests.RequestException as exc:
            classified = classify_request_exception(exc)
            record = _attempt_record(pool, card, started=started, finished=_now(), status_code=None, category=classified.category, error=str(classified), waited=waited)
            attempts.append(record)
            record_provider_attempt(record)
            set_provider_cooldown(card, cooldown or DEFAULT_COOLDOWN_SECONDS)
            if len(attempts) >= maximum:
                raise ProviderRoutingError(str(classified), attempts=attempts) from exc
            if cooldown > 0:
                time.sleep(min(cooldown, 5.0))
        except (ValueError, OSError) as exc:
            classified = ProviderCallError(f"Resposta/IO inválido do provider: {str(exc)[:220]}", category="payload", retryable=False)
            record = _attempt_record(pool, card, started=started, finished=_now(), status_code=None, category=classified.category, error=str(classified), waited=waited)
            attempts.append(record)
            record_provider_attempt(record)
            raise ProviderRoutingError(str(classified), attempts=attempts) from exc
    raise ProviderRoutingError(f"Todos os providers do pool {pool} falharam.", attempts=attempts)


def route_llm_json(settings: Mapping[str, Any], system_prompt: str, user_prompt: str) -> RoutedResponse:
    """Send an OpenAI-compatible JSON chat call through the LLM pool."""
    optimized_user_prompt = compress_text(user_prompt, "json", settings=settings) if len(str(user_prompt or "")) >= 50000 else None
    prepared_user_prompt = optimized_user_prompt.content if optimized_user_prompt is not None else user_prompt
    def request(card: dict[str, Any]) -> Any:
        definition = provider_definition(card.get("provider"))
        base_url = str(card.get("base_url") or definition.default_base_url).strip().rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        api_key = str(card.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body = {
            "model": str(card.get("model") or "").strip(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prepared_user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if not body["model"]:
            raise ProviderCallError("O cartão LLM não tem modelo configurado.", category="payload", retryable=False)
        return requests.post(endpoint, headers=headers, json=body, timeout=120)

    return route_json_request(settings, pool=POOL_LLM, cards=None, request=request)
