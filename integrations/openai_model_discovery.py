"""Discovery of models from OpenAI-compatible providers such as NVIDIA NIM."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


LOGGER = logging.getLogger(__name__)


DEFAULT_NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_TIMEOUT_SECONDS = 12
MAX_MODEL_IDS = 2000


class ModelDiscoveryError(ValueError):
    """Raised when an OpenAI-compatible model list cannot be loaded safely."""


class OpenAICompatibleAPIError(ValueError):
    """Raised when an authenticated OpenAI-compatible API check fails."""


def _normalise_http_base_url(base_url: str, *, error_type: type[Exception]) -> str:
    """Keep only the HTTP origin/path used to build OpenAI-compatible endpoints."""
    raw = str(base_url or "").strip()
    if not raw:
        raise error_type("Informe a Base URL antes da chamada.")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise error_type("A Base URL não é válida.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise error_type("A Base URL deve começar por http:// ou https://.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def models_endpoint(base_url: str) -> str:
    """Return the ``/models`` endpoint for an OpenAI-compatible base URL."""
    value = _normalise_http_base_url(base_url, error_type=ModelDiscoveryError)
    if value.endswith("/models"):
        return value
    return f"{value}/models"


def chat_completions_endpoint(base_url: str) -> str:
    """Return the Chat Completions endpoint for an OpenAI-compatible base URL."""
    value = _normalise_http_base_url(base_url, error_type=OpenAICompatibleAPIError)
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/models"):
        value = value.removesuffix("/models")
    return f"{value}/chat/completions"


def validate_openrouter_api_key(
    api_key: str,
    base_url: str,
    model: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Validate an OpenRouter key and model without spending credits on a chat call."""
    token = str(api_key or "").strip()
    model_id = str(model or "").strip()
    if not token:
        raise OpenAICompatibleAPIError("Informe a API key antes do teste.")
    if not model_id:
        raise OpenAICompatibleAPIError("Informe o modelo antes do teste.")

    base = _normalise_http_base_url(base_url, error_type=OpenAICompatibleAPIError)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    key_endpoint = f"{base}/key"
    try:
        key_response = requests.get(key_endpoint, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise OpenAICompatibleAPIError("Não foi possível contactar o OpenRouter para validar a API key.") from exc

    if key_response.status_code in (401, 403):
        raise OpenAICompatibleAPIError(
            f"A API key do OpenRouter foi recusada (HTTP {key_response.status_code}). Verifique a credencial."
        )
    if key_response.status_code >= 400:
        raise OpenAICompatibleAPIError(
            f"O diagnóstico da API key do OpenRouter devolveu HTTP {key_response.status_code}."
        )

    try:
        available_models = fetch_openai_compatible_models(token, base, timeout=timeout)
    except ModelDiscoveryError as exc:
        raise OpenAICompatibleAPIError(
            "A API key foi aceite, mas não foi possível consultar o catálogo de modelos OpenRouter."
        ) from exc
    if model_id not in available_models:
        raise OpenAICompatibleAPIError(
            f"A API key OpenRouter foi validada, mas o modelo '{model_id}' não está no catálogo actual. "
            "Clique em Consultar modelos e seleccione um modelo disponível."
        )


def validate_openai_compatible_api_key(
    api_key: str,
    base_url: str,
    model: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Validate credentials with one minimal authenticated Chat Completions call."""
    token = str(api_key or "").strip()
    model_id = str(model or "").strip()
    if not token:
        raise OpenAICompatibleAPIError("Informe a API key antes do teste.")
    if not model_id:
        raise OpenAICompatibleAPIError("Informe o modelo antes do teste.")

    endpoint = chat_completions_endpoint(base_url)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Responda apenas OK."}],
        "max_tokens": 1,
        "temperature": 0,
    }
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise OpenAICompatibleAPIError(f"Não foi possível testar {endpoint}: {exc}") from exc

    if response.status_code >= 400:
        if response.status_code in (401, 403):
            raise OpenAICompatibleAPIError(
                f"O endpoint recusou a API key (HTTP {response.status_code}). Verifique a API key."
            )
        if response.status_code == 404 and "openrouter.ai" in str(urlsplit(base_url).netloc).casefold():
            raise OpenAICompatibleAPIError(
                "O OpenRouter devolveu HTTP 404. Confirme a Base URL "
                "https://openrouter.ai/api/v1 e seleccione um modelo válido do catálogo "
                "(por exemplo, openai/gpt-4o-mini). O teste envia POST para "
                "https://openrouter.ai/api/v1/chat/completions."
            )
        raise OpenAICompatibleAPIError(f"O endpoint de teste devolveu HTTP {response.status_code}.")


def normalize_model_ids(payload: Any) -> list[str]:
    """Extract unique model IDs from the standard OpenAI response shape."""
    if isinstance(payload, dict):
        collection = payload.get("data")
        if collection is None:
            collection = payload.get("models")
    elif isinstance(payload, list):
        collection = payload
    else:
        collection = None

    if not isinstance(collection, list):
        raise ModelDiscoveryError("A resposta de modelos não tem uma lista data válida.")

    model_ids: set[str] = set()
    for item in collection:
        if isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
        elif isinstance(item, str):
            model_id = item
        else:
            model_id = None
        if isinstance(model_id, str) and model_id.strip():
            model_ids.add(model_id.strip())

    if not model_ids:
        raise ModelDiscoveryError("O endpoint não devolveu nenhum identificador de modelo.")
    return sorted(model_ids, key=str.casefold)[:MAX_MODEL_IDS]


def fetch_openai_compatible_models(
    api_key: str,
    base_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """Fetch model IDs without exposing the API key in errors or logs."""
    endpoint = models_endpoint(base_url)
    headers = {"Accept": "application/json"}
    token = str(api_key or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(endpoint, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise ModelDiscoveryError(f"Não foi possível consultar {endpoint}: {exc}") from exc

    if response.status_code >= 400:
        if response.status_code in (401, 403):
            raise ModelDiscoveryError(
                f"O endpoint recusou a credencial (HTTP {response.status_code}). Verifique a API key."
            )
        raise ModelDiscoveryError(f"O endpoint devolveu HTTP {response.status_code}.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ModelDiscoveryError("O endpoint devolveu uma resposta que não é JSON.") from exc
    return normalize_model_ids(payload)


def fetch_together_models(
    api_key: str,
    base_url: str = "https://api.together.ai/v1",
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """Fetch Together AI models with a provider-specific, redacted diagnostic."""
    token = str(api_key or "").strip()
    endpoint = models_endpoint(base_url)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(endpoint, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        LOGGER.error("Together AI model query failed endpoint=%s error=%s", endpoint, str(exc)[:300])
        raise ModelDiscoveryError(f"Não foi possível consultar {endpoint}: {exc}") from exc
    if response.status_code >= 400:
        detail = str(response.text or "").replace(token, "[REDACTED]").strip()[:500]
        LOGGER.error("Together AI model query failed status=%s endpoint=%s response=%s", response.status_code, endpoint, detail)
        if response.status_code in (401, 403):
            raise ModelDiscoveryError(f"O endpoint Together AI recusou a credencial (HTTP {response.status_code}).")
        raise ModelDiscoveryError(f"O endpoint Together AI devolveu HTTP {response.status_code}: {detail or 'sem mensagem'}")
    try:
        payload = response.json()
    except ValueError as exc:
        detail = str(response.text or "").replace(token, "[REDACTED]").strip()[:500]
        LOGGER.error("Together AI model query returned non-JSON status=%s endpoint=%s response=%s", response.status_code, endpoint, detail)
        raise ModelDiscoveryError("O endpoint Together AI devolveu uma resposta que não é JSON.") from exc
    return normalize_model_ids(payload)


def fetch_huggingface_text_to_image_models(
    api_key: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    limit: int = 2000,
) -> list[str]:
    """List only public Hugging Face models tagged with ``text-to-image``."""
    token = str(api_key or "").strip()
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(
            "https://huggingface.co/api/models",
            params={"pipeline_tag": "text-to-image", "limit": min(max(int(limit), 1), MAX_MODEL_IDS), "sort": "downloads", "direction": -1},
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ModelDiscoveryError(f"Não foi possível consultar o catálogo text-to-image da Hugging Face: {exc}") from exc
    if response.status_code >= 400:
        raise ModelDiscoveryError(f"O catálogo text-to-image da Hugging Face devolveu HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ModelDiscoveryError("O catálogo Hugging Face devolveu uma resposta que não é JSON.") from exc
    if not isinstance(payload, list):
        raise ModelDiscoveryError("O catálogo Hugging Face não devolveu uma lista de modelos.")
    models = sorted({str(item.get("id") or "").strip() for item in payload if isinstance(item, dict) and str(item.get("id") or "").strip()}, key=str.casefold)
    if not models:
        raise ModelDiscoveryError("A Hugging Face não devolveu modelos com pipeline text-to-image.")
    return models[:MAX_MODEL_IDS]


def fetch_replicate_models(
    api_key: str,
    base_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """Fetch Replicate model slugs with their latest version IDs.

    Replicate is not OpenAI-compatible: its catalog uses ``results`` rather
    than ``data`` and the latest version ID is required by predictions.
    """
    token = str(api_key or "").strip()
    if not token:
        raise ModelDiscoveryError("Informe a API key Replicate antes de consultar os modelos.")
    base = _normalise_http_base_url(base_url, error_type=ModelDiscoveryError)
    endpoint = base if base.endswith("/models") else f"{base}/models"
    try:
        response = requests.get(
            endpoint,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ModelDiscoveryError(f"Não foi possível consultar {endpoint}: {exc}") from exc
    if response.status_code >= 400:
        if response.status_code in (401, 403):
            raise ModelDiscoveryError(f"O endpoint Replicate recusou a API key (HTTP {response.status_code}).")
        raise ModelDiscoveryError(f"O endpoint Replicate devolveu HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ModelDiscoveryError("O endpoint Replicate devolveu uma resposta que não é JSON.") from exc
    entries = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ModelDiscoveryError("A resposta Replicate não tem uma lista results válida.")
    models: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner") or "").strip()
        name = str(item.get("name") or "").strip()
        latest = item.get("latest_version")
        version = str(latest.get("id") or "").strip() if isinstance(latest, dict) else ""
        if owner and name and version:
            models.add(f"{owner}/{name}:{version}")
    if not models:
        raise ModelDiscoveryError("O endpoint Replicate não devolveu modelos com versão disponível.")
    return sorted(models, key=str.casefold)[:MAX_MODEL_IDS]


def validate_paligemma_api_key(
    api_key: str,
    base_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Validate the NIM credential through its authenticated model catalog."""
    token = str(api_key or "").strip()
    if not token:
        raise OpenAICompatibleAPIError("Informe a API key antes do teste.")
    configured = str(base_url or DEFAULT_NVIDIA_NIM_BASE_URL).rstrip("/")
    if configured.endswith("/chat/completions"):
        configured = configured.removesuffix("/chat/completions")
    endpoint = configured if configured.endswith("/models") else f"{configured}/models"
    try:
        response = requests.get(
            endpoint,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OpenAICompatibleAPIError(f"Não foi possível testar o catálogo NVIDIA NIM: {exc}") from exc
    if response.status_code >= 400:
        if response.status_code in (401, 403):
            raise OpenAICompatibleAPIError(f"O catálogo NVIDIA NIM recusou a API key (HTTP {response.status_code}).")
        raise OpenAICompatibleAPIError(f"O catálogo NVIDIA NIM devolveu HTTP {response.status_code}.")
