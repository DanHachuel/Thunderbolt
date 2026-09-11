"""Provider adapters for the independent image and video pools.

Adapters are intentionally small and response-shape tolerant: providers can return
base64, data URLs, direct URLs, or asynchronous task identifiers. The router owns
failover; this module owns provider-specific HTTP contracts.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin

import requests

from .media_providers import (
    INTERNAL_IMAGE_ASPECT_RATIO,
    INTERNAL_IMAGE_SIZE,
    INTERNAL_VIDEO_ASPECT_RATIO,
    INTERNAL_VIDEO_SIZE,
    media_cards_for_pool,
    media_provider_definition,
)
from .provider_routing import (
    POOL_IMAGE,
    POOL_VIDEO,
    ProviderCallError,
    ProviderRoutingError,
    route_json_request,
)
from .storage import STORAGE, ensure_storage, write_json
from .thumbnail_generation import _compose_thumbnail_prompt, generate_thumbnail_image, infer_thumbnail_aspect_ratio, normalize_thumbnail_bytes
from .canva_client import CanvaClient
from .canva_mcp_workflow import run_direct_canva_thumbnail


class MediaGenerationError(RuntimeError):
    """Raised when an image/video adapter cannot produce a usable artifact."""

    def __init__(self, message: str, *, provider_errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.provider_errors = list(provider_errors or [])


def format_media_generation_error(exc: MediaGenerationError, *, operation: str = "gerar a imagem") -> str:
    """Return a concise Portuguese diagnostic instead of exposing only a traceback."""
    text = str(exc or "").strip()
    errors = list(exc.provider_errors or [])
    if errors:
        status_codes = [int(match.group(1)) for item in errors for match in [re.search(r"\bHTTP\s+(\d{3})\b", str(item), re.IGNORECASE)] if match]
        if any(code in {401, 403} for code in status_codes):
            code = f"IMG_AUTH_HTTP_{next(code for code in status_codes if code in {401, 403})}"
            cause = "a API key está ausente, inválida ou sem permissão para este provider"
            action = "confirme a API key, o endpoint e as permissões em Configurações > Configuração API > API Keys"
        elif any(code == 402 for code in status_codes):
            code, cause, action = "IMG_QUOTA_HTTP_402", "o provider recusou a chamada por quota, créditos ou facturação", "confirme o saldo/plano do provider ou seleccione outro provider activo"
        elif any(code == 404 for code in status_codes):
            code, cause, action = "IMG_ENDPOINT_HTTP_404", "o endpoint ou modelo configurado não existe", "confirme a Base URL e o Modelo no cartão do provider"
        elif any(code in {408, 429} for code in status_codes):
            code = f"IMG_RATE_LIMIT_HTTP_{next(code for code in status_codes if code in {408, 429})}"
            cause = "o provider está limitado ou não respondeu dentro do tempo permitido"
            action = "aguarde alguns instantes, reduza a frequência ou use outro provider activo"
        elif any(code >= 500 for code in status_codes):
            code, cause, action = "IMG_PROVIDER_HTTP_5XX", "o serviço do provider devolveu um erro temporário", "tente novamente mais tarde ou use outro provider activo"
        else:
            code, cause, action = "IMG_PROVIDER_REQUEST_FAILED", "o provider rejeitou a chamada", "confirme o modelo, endpoint, formato da API key e os campos obrigatórios"
        details = "; ".join(str(item)[:220] for item in errors)
        return f"Não foi possível {operation}. Código: {code}. Causa provável: {cause}. Acção: {action}. Detalhes: {details}"
    if "Não existem providers activos" in text:
        return f"Não foi possível {operation}. Código: IMG_NO_ACTIVE_PROVIDER. Causa provável: não existe nenhum provider activo no pool de imagem. Acção: active um cartão em Configurações > Configuração API > LLM — providers e modelos / Imagem e Video IA."
    return f"Não foi possível {operation}. Código: IMG_GENERATION_FAILED. Causa: {text or 'o provider não devolveu uma imagem utilizável'}. Acção: confirme a configuração do provider e tente novamente."


AGNES_IMAGE_MODEL = "agnes-image-2.1-flash"
AGNES_IMAGE_TIMEOUT_SECONDS = 120
AGNES_MAX_PROMPT_CHARS = 9500


def _api_key(card: Mapping[str, Any]) -> str:
    return str(card.get("api_key") or "").strip()


def _model(card: Mapping[str, Any]) -> str:
    return str(card.get("model") or "").strip()


def _hydrate_media_card(settings: Mapping[str, Any], card: Mapping[str, Any]) -> dict[str, Any]:
    """Restore credentials when a persisted thumbnail task contains an old card snapshot."""
    effective = dict(card)
    if str(effective.get("api_key") or "").strip():
        return effective
    card_id = str(effective.get("id") or "").strip()
    stored_cards = settings.get("media_provider_cards")
    if isinstance(stored_cards, list):
        for stored in stored_cards:
            if isinstance(stored, Mapping) and card_id and str(stored.get("id") or "").strip() == card_id:
                key = str(stored.get("api_key") or stored.get("key") or "").strip()
                if key:
                    effective["api_key"] = key
                    break
    if not str(effective.get("api_key") or "").strip() and str(effective.get("provider") or "").strip().lower() == "agnes":
        for key_name in ("agnes_api_key", "agnes_ai_api_key", "agnes_token", "media_agnes_api_key"):
            key = str(settings.get(key_name) or "").strip()
            if key:
                effective["api_key"] = key
                break
    return effective


def _base_url(card: Mapping[str, Any]) -> str:
    return str(card.get("base_url") or "").strip().rstrip("/")


def _headers(card: Mapping[str, Any], *, fal: bool = False) -> dict[str, str]:
    key = _api_key(card)
    provider = str(card.get("provider") or "").strip().lower()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        if provider == "heygen":
            headers["X-Api-Key"] = key
        else:
            headers["Authorization"] = f"Key {key}" if fal else f"Bearer {key}"
    return headers


def _fit_provider_prompt(prompt: str, provider: str) -> str:
    """Keep provider-specific prompt limits from turning a thumbnail into a 400."""
    text = str(prompt or "").strip()
    if provider != "agnes" or len(text) <= AGNES_MAX_PROMPT_CHARS:
        return text
    # Keep both the visual brief and the mandatory lettering layer at the end.
    tail_size = min(1800, AGNES_MAX_PROMPT_CHARS // 4)
    head_size = AGNES_MAX_PROMPT_CHARS - tail_size - 80
    return f"{text[:head_size].rstrip()}\n\n[Prompt longo resumido para o limite Agnes AI.]\n\n{text[-tail_size:].lstrip()}"


def _append_generation_constraints(
    prompt: str,
    *,
    kind: str,
    aspect_ratio: str = "",
    size: str = "",
) -> str:
    """Append controlled rendering constraints without exposing editable UI fields."""
    clean = str(prompt or "").strip()
    if kind == "image":
        ratio = str(aspect_ratio or INTERNAL_IMAGE_ASPECT_RATIO).strip()
        resolution = str(size or INTERNAL_IMAGE_SIZE).strip()
        constraints = f"Target image composition: {ratio} aspect ratio, {resolution} resolution."
    else:
        ratio = str(aspect_ratio or INTERNAL_VIDEO_ASPECT_RATIO).strip()
        resolution = str(size or INTERNAL_VIDEO_SIZE).strip()
        constraints = f"Target video composition: {ratio} aspect ratio, {resolution} resolution."
    if not clean:
        return constraints
    return f"{clean}\n\n{constraints}"


def _decode_data(value: Any) -> bytes | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None


def _image_value(payload: Any) -> tuple[bytes | None, str]:
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload), ""
    if not isinstance(payload, Mapping):
        return None, ""
    direct = payload.get("image") or payload.get("output_image")
    if isinstance(direct, Mapping):
        direct = direct.get("data") or direct.get("url")
    data = _decode_data(direct)
    if data:
        return data, ""
    if isinstance(direct, str) and direct.startswith(("http://", "https://")):
        return None, direct
    entries = payload.get("data") or payload.get("outputs") or payload.get("images")
    if isinstance(entries, list) and entries:
        first = entries[0]
        if isinstance(first, Mapping):
            data = _decode_data(first.get("b64_json") or first.get("base64") or first.get("data"))
            if data:
                return data, ""
            url = str(first.get("url") or first.get("image_url") or "").strip()
            if url:
                return None, url
    output = payload.get("output")
    if isinstance(output, list) and output:
        output = output[0]
    if isinstance(output, Mapping):
        output = output.get("url") or output.get("image_url") or output.get("image")
    if isinstance(output, str):
        if output.startswith(("http://", "https://")):
            return None, output
        output_data = _decode_data(output)
        if output_data:
            return output_data, ""
    result = payload.get("result")
    if isinstance(result, Mapping):
        data = _decode_data(result.get("image") or result.get("b64_json") or result.get("data"))
        if data:
            return data, ""
        url = str(result.get("url") or result.get("image_url") or "").strip()
        if url:
            return None, url
    return None, ""


def _image_request_id(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    nested = payload.get("data")
    if isinstance(nested, Mapping):
        task_id = str(nested.get("taskId") or "").strip()
        if task_id:
            return task_id
    for key in ("id", "prediction_id", "request_id", "task_id", "job_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _poll_image(card: Mapping[str, Any], request_id: str, *, attempts: int = 24, interval_seconds: float = 5.0) -> tuple[bytes | None, str]:
    """Resolve a Replicate image prediction without exposing its token."""
    style = str(card.get("api_style") or media_provider_definition(card.get("provider")).api_style)
    base = _base_url(card)
    endpoint = str(card.get("status_endpoint") or "").strip().replace("{id}", request_id)
    if not endpoint:
        if style != "replicate":
            return None, ""
        endpoint = f"{base}/predictions/{request_id}"
    for index in range(max(1, attempts)):
        try:
            response = requests.get(endpoint, headers=_headers(card), timeout=60)
            if response.status_code >= 400:
                raise MediaGenerationError(f"Consulta de imagem devolveu HTTP {response.status_code}.")
            payload = response.json()
        except requests.RequestException as exc:
            raise MediaGenerationError(f"Falha ao consultar a imagem: {str(exc)[:180]}") from exc
        image_bytes, url = _image_value(payload if isinstance(payload, Mapping) else {})
        if image_bytes or url:
            return image_bytes, url
        status = str((payload or {}).get("status") or "").lower() if isinstance(payload, Mapping) else ""
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise MediaGenerationError("O provider marcou a tarefa de imagem como falhada.")
        if index + 1 < attempts:
            time.sleep(max(0.2, interval_seconds))
    raise MediaGenerationError("O provider de imagem não concluiu dentro do limite de polling.")


def _download_or_write(
    image_bytes: bytes | None,
    url: str,
    destination: Path,
    card: Mapping[str, Any],
    *,
    aspect_ratio: str = "16:9",
) -> Path:
    if image_bytes is None and url:
        try:
            response = requests.get(url, headers={"Authorization": f"Bearer {_api_key(card)}"} if _api_key(card) else {}, timeout=180)
            response.raise_for_status()
            image_bytes = response.content
        except requests.RequestException as exc:
            raise MediaGenerationError(f"Não foi possível descarregar a imagem devolvida pelo provider: {exc}") from exc
    if not image_bytes:
        raise MediaGenerationError("O provider concluiu a chamada mas não devolveu uma imagem utilizável.")
    try:
        image_bytes = normalize_thumbnail_bytes(image_bytes, aspect_ratio)
    except Exception as exc:
        raise MediaGenerationError(str(exc)) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image_bytes)
    return destination


def _image_endpoint(card: Mapping[str, Any]) -> str:
    definition = media_provider_definition(card.get("provider"))
    style = str(card.get("api_style") or definition.api_style)
    base = _base_url(card)
    explicit = str(card.get("image_endpoint") or "").strip()
    if explicit:
        return explicit
    if style == "openrouter":
        return f"{base}/images"
    if style == "kie":
        return f"{base}/jobs/createTask"
    if style in {"openai_compatible", "huggingface", "agnes"}:
        return f"{base}/images/generations"
    if style == "replicate":
        return f"{base}/predictions"
    if style == "cloudflare":
        account_id = str(card.get("account_id") or "").strip()
        if not account_id:
            raise MediaGenerationError("Cloudflare Workers AI requer Account ID no cartão de media.")
        model = _model(card) or "@cf/stabilityai/stable-diffusion-xl-base-1.0"
        model = model if model.startswith("@") else f"@{model}"
        return f"{base}/accounts/{account_id}/ai/run/{model}"
    if style == "fal_queue":
        if not _model(card):
            raise MediaGenerationError("FAL AI requer o identificador da rota/modelo para gerar imagem.")
        return f"{base}/{_model(card).lstrip('/')}"
    if style == "dashscope":
        return f"{base}/services/aigc/text2image/image-synthesis"
    raise MediaGenerationError(f"O provider {card.get('provider')} não tem endpoint de imagem configurado.")


def _thumbnail_aspect_ratio(thumbnail_blueprint: Mapping[str, Any] | None, prompt: str = "") -> str:
    return infer_thumbnail_aspect_ratio(prompt, dict(thumbnail_blueprint or {}))


def _image_request(card: dict[str, Any], prompt: str, *, topic: str = "", lettering_text: str = "", lettering_prompt: str = "", thumbnail_blueprint: Mapping[str, Any] | None = None) -> Any:
    provider = str(card.get("provider") or "").strip().lower()
    style = str(card.get("api_style") or media_provider_definition(provider).api_style)
    endpoint = _image_endpoint(card)
    image_prompt, _headline = _compose_thumbnail_prompt(
        prompt,
        topic=topic,
        lettering_text=lettering_text,
        lettering_prompt=lettering_prompt,
    )
    aspect_ratio = _thumbnail_aspect_ratio(thumbnail_blueprint, prompt)
    requested_size = ("1024x1792" if aspect_ratio == "9:16" else "1792x1024") if provider == "pollinations" else ("720x1280 minimum" if aspect_ratio == "9:16" else "1280x720 minimum")
    constrained_prompt = _append_generation_constraints(
        image_prompt,
        kind="image",
        aspect_ratio=aspect_ratio,
        size=requested_size,
    )
    constrained_prompt = _fit_provider_prompt(constrained_prompt, provider)
    if style == "cloudflare":
        return requests.post(endpoint, headers=_headers(card), json={"prompt": constrained_prompt}, timeout=180)
    if style == "fal_queue":
        return requests.post(endpoint, headers=_headers(card, fal=True), json={"prompt": constrained_prompt, "num_images": 1}, timeout=180)
    if style == "dashscope":
        body = {"model": _model(card), "input": {"prompt": constrained_prompt}, "parameters": {"n": 1}}
        return requests.post(endpoint, headers=_headers(card), json=body, timeout=180)
    if style == "replicate":
        body = {"version": _model(card), "input": {"prompt": constrained_prompt}}
        return requests.post(endpoint, headers=_headers(card), json=body, timeout=180)
    if style == "kie":
        body = {
            "model": _model(card),
            "input": {"prompt": constrained_prompt, "aspect_ratio": aspect_ratio, "resolution": "1K"},
        }
        return requests.post(endpoint, headers=_headers(card), json=body, timeout=180)
    if provider == "agnes":
        body = {
            "model": _model(card) or AGNES_IMAGE_MODEL,
            "prompt": constrained_prompt,
            "size": "1K",
            "ratio": aspect_ratio,
            "return_base64": True,
            "extra_body": {"response_format": "b64_json"},
        }
        return requests.post(endpoint, headers=_headers(card), json=body, timeout=AGNES_IMAGE_TIMEOUT_SECONDS)
    if style == "openrouter":
        return requests.post(
            endpoint,
            headers=_headers(card),
            json={"model": _model(card), "prompt": constrained_prompt, "n": 1, "aspect_ratio": aspect_ratio},
            timeout=180,
        )
    body = {"model": _model(card), "prompt": constrained_prompt, "n": 1, "response_format": "b64_json"}
    if provider == "pollinations":
        body["size"] = "1024x1792" if aspect_ratio == "9:16" else "1792x1024"
    return requests.post(endpoint, headers=_headers(card), json=body, timeout=180)


def generate_image_for_card(
    settings: Mapping[str, Any],
    card: Mapping[str, Any],
    prompt: str,
    *,
    topic: str = "",
    variant_index: int = 0,
    lettering_text: str = "",
    lettering_prompt: str = "",
    reference_image: Path | None = None,
    thumbnail_blueprint: Mapping[str, Any] | None = None,
) -> Path:
    """Generate one image with the selected media card."""
    card = _hydrate_media_card(settings, card)
    provider = str(card.get("provider") or "").strip().lower()
    if provider == "canva":
        ensure_storage()
        export_format = str(card.get("export_format") or "png").lower()
        destination = STORAGE / "thumbnails" / f"canva-{abs(hash((topic, prompt, variant_index))) & 0xffffffffffffffff:x}.{export_format if export_format in {'png', 'jpg'} else 'png'}"
        card["output_path"] = str(destination)
        blueprint = dict(thumbnail_blueprint or {})
        if not str(blueprint.get("content") or "").strip():
            raise MediaGenerationError("Canva exige um Thumbnail Blueprint local válido.")
        try:
            return run_direct_canva_thumbnail(
                title=str(topic or "Thunderbolt thumbnail")[:255],
                topic=topic,
                prompt=prompt,
                blueprint=blueprint,
                destination=destination,
                width=int(card.get("thumbnail_width") or 1280),
                height=int(card.get("thumbnail_height") or 720),
                quality=str(card.get("export_quality") or "medium"),
            )
        except Exception as exc:
            raise MediaGenerationError(str(exc)) from exc

        def save_token(token: Mapping[str, Any]) -> None:
            updated = dict(settings)
            saved_cards = [dict(item) for item in updated.get("media_provider_cards", []) if isinstance(item, Mapping)]
            for saved_card in saved_cards:
                if str(saved_card.get("id")) == str(card.get("id")):
                    saved_card["oauth_token"] = dict(token)
            updated["media_provider_cards"] = saved_cards
            write_json("settings.json", updated)
        try:
            return CanvaClient(card, token_saver=save_token).create_and_export_thumbnail(
                title=str(topic or "Thunderbolt thumbnail")[:255],
                width=int(card.get("thumbnail_width") or 1280),
                height=int(card.get("thumbnail_height") or 720),
            )
        except Exception as exc:
            raise MediaGenerationError(str(exc)) from exc
    aspect_ratio = _thumbnail_aspect_ratio(thumbnail_blueprint, prompt)
    if provider == "nano_banana":
        merged = dict(settings)
        merged["gemini_image_api_key"] = _api_key(card)
        merged["gemini_image_model"] = _model(card) or merged.get("gemini_image_model") or "gemini-3.1-flash-image"
        merged["gemini_image_aspect_ratio"] = str(card.get("aspect_ratio") or INTERNAL_IMAGE_ASPECT_RATIO)
        merged["gemini_image_size"] = str(card.get("image_size") or INTERNAL_IMAGE_SIZE)
        try:
            return generate_thumbnail_image(
                merged,
                _append_generation_constraints(
                    prompt,
                    kind="image",
                    aspect_ratio=aspect_ratio,
                    size="720x1280 minimum" if aspect_ratio == "9:16" else "1280x720 minimum",
                ),
                topic=topic,
                variant_index=variant_index,
                lettering_text=lettering_text,
                lettering_prompt=lettering_prompt,
                reference_image=reference_image,
                aspect_ratio=aspect_ratio,
                lock_aspect_ratio=True,
            )
        except Exception as exc:
            raise MediaGenerationError(str(exc)) from exc

    ensure_storage()
    destination = STORAGE / "thumbnails" / f"media-{provider}-{abs(hash((topic, prompt, variant_index))) & 0xffffffffffffffff:x}.jpg"

    if provider == "huggingface":
        model = _model(card)
        token = _api_key(card)
        if not model:
            raise MediaGenerationError("Hugging Face requer a selecção de um modelo text-to-image.")
        try:
            image_prompt, _headline = _compose_thumbnail_prompt(
                prompt,
                topic=topic,
                lettering_text=lettering_text,
                lettering_prompt=lettering_prompt,
            )
            constrained_prompt = _append_generation_constraints(
                image_prompt,
                kind="image",
                aspect_ratio=aspect_ratio,
                size="720x1280 minimum" if aspect_ratio == "9:16" else "1280x720 minimum",
            )
            from huggingface_hub import InferenceClient
            image = InferenceClient(token=token or None, provider="hf-inference").text_to_image(
                prompt=constrained_prompt,
                model=model,
            )
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return _download_or_write(buffer.getvalue(), "", destination, card, aspect_ratio=aspect_ratio)
        except Exception as exc:
            raise MediaGenerationError(f"Hugging Face text-to-image falhou: {str(exc)[:240]}") from exc

    def request(current: dict[str, Any]) -> Any:
        return _image_request(current, prompt, topic=topic, lettering_text=lettering_text, lettering_prompt=lettering_prompt, thumbnail_blueprint=thumbnail_blueprint)

    try:
        routed = route_json_request(settings, pool=POOL_IMAGE, cards=[card], request=request)
    except ProviderRoutingError as exc:
        attempts = list(getattr(exc, "attempts", []) or [])
        provider_errors = []
        for attempt in attempts:
            provider = str(attempt.get("provider") or "provider")
            status_code = attempt.get("status_code")
            error = str(attempt.get("error") or "falha sem detalhe")
            prefix = f"HTTP {int(status_code)}: " if status_code else ""
            provider_errors.append(f"{provider}: {prefix}{error[:180]}")
        raise MediaGenerationError(str(exc), provider_errors=provider_errors) from exc
    image_bytes, url = _image_value(routed.payload)
    if not image_bytes and not url:
        request_id = _image_request_id(routed.payload)
        style = str(routed.card.get("api_style") or media_provider_definition(routed.card.get("provider")).api_style)
        if request_id and style == "replicate":
            image_bytes, url = _poll_image(routed.card, request_id)
        elif request_id and style == "kie":
            urls = _poll_kie_task(routed.card, request_id, endpoint="/jobs/recordInfo", veo=False)
            url = urls[0] if urls else ""
    return _download_or_write(image_bytes, url, destination, routed.card, aspect_ratio=aspect_ratio)


def _is_retryable_media_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if any(marker in text for marker in ("http 400", "http 401", "http 403", "http 404", "invalid request", "missing", "não tem endpoint")):
        return False
    return any(marker in text for marker in ("http 402", "http 408", "http 425", "http 429", "http 500", "http 502", "http 503", "http 504", "timeout", "timed out", "connection", "temporarily", "cooldown"))


def generate_image_from_pool(
    settings: Mapping[str, Any],
    prompt: str,
    *,
    topic: str = "",
    variant_index: int = 0,
    lettering_text: str = "",
    lettering_prompt: str = "",
    reference_image: Path | None = None,
    thumbnail_only: bool = False,
    thumbnail_blueprint: Mapping[str, Any] | None = None,
) -> Path:
    """Try eligible image cards in priority order, without cross-pool fallback."""
    cards = media_cards_for_pool(settings, "image", thumbnail_only=True) if thumbnail_only else media_cards_for_pool(settings, "image")
    if not cards:
        raise MediaGenerationError("Não existem providers activos no pool de imagem.")
    errors: list[str] = []
    for card in cards:
        try:
            return generate_image_for_card(
                settings,
                card,
                prompt,
                topic=topic,
                variant_index=variant_index,
                lettering_text=lettering_text,
                lettering_prompt=lettering_prompt,
                reference_image=reference_image,
                thumbnail_blueprint=thumbnail_blueprint,
            )
        except MediaGenerationError as exc:
            errors.append(f"{card.get('provider')}: {str(exc)[:180]}")
            if not _is_retryable_media_error(exc):
                raise
    details = "\n".join(f"- {item}" for item in errors) if errors else "- Nenhum detalhe foi devolvido pelos providers."
    raise MediaGenerationError(
        "Todos os providers do pool de imagem falharam. Tentativas realizadas:\n" + details,
        provider_errors=errors,
    )


def _video_endpoint(card: Mapping[str, Any]) -> str:
    explicit = str(card.get("video_endpoint") or "").strip()
    if explicit:
        return explicit
    definition = media_provider_definition(card.get("provider"))
    style = str(card.get("api_style") or definition.api_style)
    base = _base_url(card)
    if style == "heygen":
        return f"{base}/v3/videos"
    if style == "fal_queue":
        if not _model(card):
            raise MediaGenerationError("FAL AI requer o identificador da rota/modelo para gerar vídeo.")
        return f"{base}/{_model(card).lstrip('/')}"
    if style == "openrouter":
        return f"{base}/videos"
    if style == "kie":
        return f"{base}/jobs/createTask"
    if style in {"openai_compatible", "agnes"}:
        return f"{base}/videos/generations"
    if style == "replicate":
        return f"{base}/predictions"
    if style == "dashscope":
        return f"{base}/services/aigc/video-generation/video-synthesis"
    raise MediaGenerationError(f"O provider {card.get('provider')} não tem endpoint de vídeo configurado.")


def _video_request(card: dict[str, Any], prompt: str, image_url: str = "", duration: int | None = None, aspect_ratio: str | None = None) -> Any:
    style = str(card.get("api_style") or media_provider_definition(card.get("provider")).api_style)
    endpoint = _video_endpoint(card)
    body: dict[str, Any] = {
        "model": _model(card),
        "prompt": _append_generation_constraints(
            prompt,
            kind="video",
            aspect_ratio=str(card.get("aspect_ratio") or ""),
            size=str(card.get("video_size") or ""),
        ),
    }
    if aspect_ratio:
        body["aspect_ratio"] = str(aspect_ratio)
    if image_url:
        body["image_url"] = image_url
    if duration is not None:
        body["duration"] = max(1, int(duration))
    if style == "openrouter":
        body["aspect_ratio"] = str(aspect_ratio or card.get("aspect_ratio") or INTERNAL_VIDEO_ASPECT_RATIO)
        body["resolution"] = str(card.get("video_size") or INTERNAL_VIDEO_SIZE)
        return requests.post(endpoint, headers=_headers(card), json=body, timeout=180)
    if style == "kie":
        input_payload: dict[str, Any] = {
            "prompt": body["prompt"],
            "aspect_ratio": str(aspect_ratio or card.get("aspect_ratio") or INTERNAL_VIDEO_ASPECT_RATIO),
            "resolution": str(card.get("video_size") or INTERNAL_VIDEO_SIZE),
        }
        if image_url:
            input_payload["imageUrls"] = [image_url]
        if duration is not None:
            input_payload["duration"] = max(1, int(duration))
        return requests.post(endpoint, headers=_headers(card), json={"model": _model(card), "input": input_payload}, timeout=180)
    if style == "heygen":
        avatar_id = str(card.get("avatar_id") or "").strip()
        if not avatar_id:
            raise MediaGenerationError("HeyGen requer Avatar ID no cartão de media para gerar vídeo.")
        heygen_body: dict[str, Any] = {
            "type": "avatar",
            "avatar_id": avatar_id,
            "script": body["prompt"],
            "aspect_ratio": str(card.get("aspect_ratio") or INTERNAL_VIDEO_ASPECT_RATIO),
            "output_format": "mp4",
        }
        voice_id = str(card.get("voice_id") or "").strip()
        if voice_id:
            heygen_body["voice_id"] = voice_id
        return requests.post(endpoint, headers=_headers(card), json=heygen_body, timeout=180)
    if style == "fal_queue":
        body.pop("model", None)
        return requests.post(endpoint, headers=_headers(card, fal=True), json=body, timeout=180)
    if style == "replicate":
        image_input_key = str(card.get("image_input_key") or "image").strip() or "image"
        input_payload = {"prompt": body["prompt"]}
        if duration is not None:
            input_payload["duration"] = max(1, int(duration))
        if image_url:
            input_payload[image_input_key] = image_url
        return requests.post(endpoint, headers=_headers(card), json={"version": _model(card), "input": input_payload}, timeout=180)
    return requests.post(endpoint, headers=_headers(card), json=body, timeout=180)


def _video_result(payload: Mapping[str, Any]) -> tuple[str, str]:
    raw_output = payload.get("output")
    if isinstance(raw_output, list) and raw_output:
        raw_output = raw_output[0]
    unsigned_urls = payload.get("unsigned_urls")
    if isinstance(unsigned_urls, list) and unsigned_urls:
        direct = str(unsigned_urls[0] or "").strip()
    else:
        direct = str(payload.get("content_url") or payload.get("video_url") or payload.get("url") or raw_output or "").strip()
    if direct.startswith(("http://", "https://")):
        return direct, ""
    result = payload.get("result")
    if isinstance(result, Mapping):
        direct = str(result.get("video_url") or result.get("url") or result.get("output") or "").strip()
        if direct:
            return direct, ""
    for key in ("request_id", "id", "task_id", "job_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return "", value
    data = payload.get("data")
    if isinstance(data, Mapping):
        direct = str(data.get("video_url") or data.get("url") or "").strip()
        if direct.startswith(("http://", "https://")):
            return direct, ""
        for key in ("video_id", "id", "request_id", "task_id", "taskId", "job_id"):
            value = str(data.get(key) or "").strip()
            if value:
                return "", value
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        first = data[0]
        direct = str(first.get("url") or first.get("video_url") or "").strip()
        if direct:
            return direct, ""
    return "", ""


def _poll_video(card: Mapping[str, Any], request_id: str, *, attempts: int = 24, interval_seconds: float = 5.0) -> str:
    definition = media_provider_definition(card.get("provider"))
    style = str(card.get("api_style") or definition.api_style)
    explicit_status = str(card.get("status_endpoint") or "").strip()
    base = _base_url(card)
    if explicit_status:
        endpoint = explicit_status.replace("{id}", request_id)
    elif style == "fal_queue":
        endpoint = f"{base}/requests/{request_id}/status"
    elif style == "replicate":
        endpoint = f"{base}/predictions/{request_id}"
    elif style == "heygen":
        endpoint = f"{base}/v3/videos/{request_id}"
    elif style == "openrouter":
        endpoint = f"{base}/videos/{request_id}"
    else:
        endpoint = f"{base}/videos/{request_id}"
    headers = _headers(card, fal=style == "fal_queue")
    for index in range(max(1, attempts)):
        try:
            response = requests.get(endpoint, headers=headers, timeout=60)
            if response.status_code >= 400:
                category = "quota" if response.status_code == 429 else "transient" if response.status_code >= 500 else "endpoint_or_model"
                raise ProviderCallError(f"Consulta de vídeo devolveu HTTP {response.status_code}.", status_code=response.status_code, category=category, retryable=category in {"quota", "transient"})
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderCallError(f"Falha ao consultar o vídeo: {str(exc)[:180]}", category="transient", retryable=True) from exc
        url, _ = _video_result(payload if isinstance(payload, Mapping) else {})
        if url:
            return url
        status_payload = payload.get("data") if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping) else payload
        status = str((status_payload or {}).get("status") or "").lower() if isinstance(status_payload, Mapping) else ""
        if status in {"failed", "error", "cancelled", "canceled"}:
            if style == "heygen" and isinstance(status_payload, Mapping):
                code = str(status_payload.get("failure_code") or "").strip()
                detail = str(status_payload.get("failure_message") or "").strip()
                suffix = f" ({code})" if code else ""
                raise ProviderCallError(f"HeyGen marcou a tarefa como falhada{suffix}: {detail or 'sem detalhe'}", category="provider", retryable=False)
            raise ProviderCallError("O provider marcou a tarefa de vídeo como falhada.", category="provider", retryable=False)
        if index + 1 < attempts:
            time.sleep(max(0.2, interval_seconds))
    raise ProviderCallError("O provider de vídeo não concluiu dentro do limite de polling.", category="transient", retryable=True)


def generate_video_for_card(
    settings: Mapping[str, Any],
    card: Mapping[str, Any],
    prompt: str,
    *,
    image_url: str = "",
    duration: int | None = None,
    aspect_ratio: str | None = None,
    output_path: Path | None = None,
) -> Path:
    """Submit and resolve one video generation request."""
    card = dict(card)
    provider = str(card.get("provider") or "").strip().lower()

    def request(current: dict[str, Any]) -> Any:
        return _video_request(current, prompt, image_url=image_url, duration=duration, aspect_ratio=aspect_ratio)

    try:
        routed = route_json_request(settings, pool=POOL_VIDEO, cards=[card], request=request)
    except ProviderRoutingError as exc:
        raise MediaGenerationError(str(exc)) from exc
    url, request_id = _video_result(routed.payload)
    if not url and request_id:
        try:
            if str(routed.card.get("api_style") or media_provider_definition(routed.card.get("provider")).api_style) == "kie":
                urls = _poll_kie_task(routed.card, request_id, endpoint="/jobs/recordInfo", veo=False)
                url = urls[0] if urls else ""
            else:
                url = _poll_video(routed.card, request_id)
        except ProviderCallError as exc:
            raise MediaGenerationError(str(exc)) from exc
    if not url:
        raise MediaGenerationError(f"O provider {provider} não devolveu URL nem identificador de vídeo.")
    destination = output_path or (STORAGE / "videos" / f"media-{provider}-{abs(hash((prompt, url))) & 0xffffffffffffffff:x}.mp4")
    try:
        response = requests.get(url, headers=_headers(routed.card), timeout=300)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MediaGenerationError(f"Não foi possível descarregar o vídeo gerado: {exc}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def generate_video_from_pool(
    settings: Mapping[str, Any],
    prompt: str,
    *,
    image_url: str = "",
    output_path: Path | None = None,
    allowed_providers: set[str] | None = None,
) -> Path:
    """Try eligible video cards in priority order, optionally restricted to a route."""
    cards = media_cards_for_pool(settings, "video")
    if allowed_providers is not None:
        allowed = {str(provider).strip().lower() for provider in allowed_providers}
        cards = [card for card in cards if str(card.get("provider") or "").strip().lower() in allowed]
    if not cards:
        raise MediaGenerationError("Não existem providers activos no pool de vídeo.")
    errors: list[str] = []
    for card in cards:
        try:
            return generate_video_for_card(settings, card, prompt, image_url=image_url, output_path=output_path)
        except MediaGenerationError as exc:
            errors.append(f"{card.get('provider')}: {str(exc)[:180]}")
            if not _is_retryable_media_error(exc):
                raise
    raise MediaGenerationError("Todos os providers do pool de vídeo falharam: " + " | ".join(errors))


KIE_FILE_UPLOAD_ENDPOINT = "https://kieai.redpandaai.co/api/file-stream-upload"
KIE_MOTION_MODEL = "kling-2.6/motion-control"
KIE_MOTION_IMAGE_MAX_BYTES = 10 * 1024 * 1024
KIE_MOTION_VIDEO_MAX_BYTES = 100 * 1024 * 1024
KIE_MOTION_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
KIE_MOTION_VIDEO_EXTENSIONS = {".mp4", ".mov"}
KIE_VEO_MODELS = {"veo3", "veo3_fast", "veo3_lite"}


def _require_kie_card(card: Mapping[str, Any]) -> dict[str, Any]:
    current = dict(card)
    if str(current.get("provider") or "").strip().lower() != "kie_ai":
        raise MediaGenerationError("Este workflow requer um cartão KIE AI activo no pool de vídeo.")
    if not _api_key(current):
        raise MediaGenerationError("Configure a API key do KIE AI em Configuração API > API Keys > Imagem e Video IA.")
    return current


def _kie_json_error(payload: Any, *, fallback: str) -> ProviderCallError | None:
    if not isinstance(payload, Mapping):
        return ProviderCallError(fallback, category="payload", retryable=False)
    try:
        code = int(payload.get("code", 200))
    except (TypeError, ValueError):
        code = 200
    if code == 200:
        return None
    category = "quota" if code in {402, 429, 433} else "credential" if code == 401 else "endpoint_or_model" if code in {404, 455, 505} else "transient" if code >= 500 else "payload"
    return ProviderCallError(str(payload.get("msg") or fallback)[:500], status_code=code, category=category, retryable=category in {"quota", "transient"})


def validate_motion_control_file(path: str | Path, *, kind: str) -> dict[str, Any]:
    """Validate KIE Motion Control local input limits before uploading it."""
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise MediaGenerationError(f"O ficheiro de {kind} não está disponível.")
    suffix = candidate.suffix.lower()
    if kind == "imagem":
        allowed, maximum = KIE_MOTION_IMAGE_EXTENSIONS, KIE_MOTION_IMAGE_MAX_BYTES
    elif kind == "vídeo":
        allowed, maximum = KIE_MOTION_VIDEO_EXTENSIONS, KIE_MOTION_VIDEO_MAX_BYTES
    else:
        raise MediaGenerationError("Tipo de input Motion Control inválido.")
    if suffix not in allowed:
        raise MediaGenerationError(f"O {kind} Motion Control deve estar em {', '.join(sorted(allowed))}.")
    size = candidate.stat().st_size
    if size <= 0:
        raise MediaGenerationError(f"O ficheiro de {kind} está vazio.")
    if size > maximum:
        raise MediaGenerationError(f"O ficheiro de {kind} excede o limite KIE de {maximum // (1024 * 1024)} MB.")
    duration = None
    if kind == "vídeo":
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise MediaGenerationError("Não foi possível verificar a duração do vídeo Motion Control: instale FFmpeg/ffprobe e tente novamente.")
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(candidate)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            duration = float(probe.stdout.strip())
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise MediaGenerationError("Não foi possível verificar a duração do vídeo Motion Control com ffprobe.") from exc
        if duration < 3 or duration > 30:
            raise MediaGenerationError(f"O vídeo Motion Control deve ter entre 3 e 30 segundos; o ficheiro tem {duration:.1f}s.")
    return {"path": str(candidate), "name": candidate.name, "size_bytes": size, "extension": suffix, "duration_seconds": duration}


def upload_kie_file(path: str | Path, card: Mapping[str, Any], *, upload_path: str = "thunderbolt/influencers") -> str:
    """Upload one local file to KIE's temporary public file store using the selected card."""
    current = _require_kie_card(card)
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise MediaGenerationError("O ficheiro seleccionado não está disponível para upload KIE.")
    mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    try:
        with candidate.open("rb") as handle:
            response = requests.post(
                KIE_FILE_UPLOAD_ENDPOINT,
                headers={"Authorization": f"Bearer {_api_key(current)}"},
                files={"file": (candidate.name, handle, mime)},
                data={"uploadPath": upload_path, "fileName": candidate.name},
                timeout=300,
            )
    except requests.RequestException as exc:
        raise MediaGenerationError(f"Falha no upload temporário do ficheiro para KIE: {str(exc)[:220]}") from exc
    if response.status_code >= 400:
        raise MediaGenerationError(f"O upload temporário KIE devolveu HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise MediaGenerationError("O upload temporário KIE devolveu uma resposta inválida.") from exc
    error = _kie_json_error(payload, fallback="O upload temporário KIE falhou.")
    if error:
        raise MediaGenerationError(str(error))
    data = payload.get("data") if isinstance(payload, Mapping) else None
    url = str((data or {}).get("downloadUrl") or (data or {}).get("fileUrl") or payload.get("downloadUrl") or payload.get("fileUrl") or "").strip() if isinstance(payload, Mapping) else ""
    if not url.startswith(("http://", "https://")):
        raise MediaGenerationError("O upload KIE terminou sem devolver um URL público temporário.")
    return url


def _download_video_url(url: str, destination: Path, *, card: Mapping[str, Any] | None = None) -> Path:
    try:
        response = requests.get(url, headers=_headers(card or {}) if card else {}, timeout=300)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MediaGenerationError(f"Não foi possível descarregar o vídeo gerado: {str(exc)[:220]}") from exc
    if not response.content:
        raise MediaGenerationError("O provider devolveu um vídeo vazio.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def _kie_result_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = value.strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = [raw] if raw.startswith(("http://", "https://")) else []
    if isinstance(value, Mapping):
        value = value.get("resultUrls") or value.get("result_urls") or value.get("urls") or []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip().startswith(("http://", "https://"))]


def _poll_kie_task(card: Mapping[str, Any], task_id: str, *, endpoint: str, attempts: int = 40, interval_seconds: float = 5.0, veo: bool = False) -> list[str]:
    base = _base_url(card) or "https://api.kie.ai/api/v1"
    url = f"{base}{endpoint}"
    for index in range(max(1, attempts)):
        try:
            response = requests.get(url, headers=_headers(card), params={"taskId": task_id}, timeout=60)
            if response.status_code >= 400:
                category = "quota" if response.status_code == 429 else "transient" if response.status_code >= 500 else "endpoint_or_model"
                raise ProviderCallError(f"Consulta KIE devolveu HTTP {response.status_code}.", status_code=response.status_code, category=category, retryable=category in {"quota", "transient"})
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderCallError(f"Falha ao consultar a tarefa KIE: {str(exc)[:220]}", category="transient", retryable=True) from exc
        error = _kie_json_error(payload, fallback="A consulta KIE devolveu um erro.")
        if error:
            raise error
        data = payload.get("data") if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping) else {}
        if veo:
            flag = data.get("successFlag")
            if str(flag) in {"2", "3"}:
                raise ProviderCallError(str(data.get("errorMessage") or payload.get("msg") or "A tarefa VEO falhou."), category="provider", retryable=False)
            response_data = data.get("response") if isinstance(data.get("response"), Mapping) else {}
            urls = _kie_result_urls(response_data.get("resultUrls") or data.get("resultUrls"))
            if str(flag) == "1" and urls:
                return urls
        else:
            state = str(data.get("state") or payload.get("state") or "").lower()
            if state in {"fail", "failed", "error", "cancelled", "canceled"}:
                raise ProviderCallError(str(data.get("failMsg") or payload.get("msg") or "A tarefa KIE falhou."), category="provider", retryable=False)
            urls = _kie_result_urls(data.get("resultJson"))
            if state == "success" and urls:
                return urls
        if index + 1 < attempts:
            time.sleep(max(0.2, interval_seconds))
    raise ProviderCallError("A tarefa KIE não concluiu dentro do limite de polling local.", category="transient", retryable=True)


def generate_motion_control_video(
    settings: Mapping[str, Any],
    card: Mapping[str, Any],
    *,
    image_url: str,
    video_url: str,
    prompt: str = "",
    output_path: Path | None = None,
) -> tuple[Path, str]:
    """Create a Kling 2.6 Motion Control video and download it locally."""
    current = _require_kie_card(card)
    if not image_url.startswith(("http://", "https://")) or not video_url.startswith(("http://", "https://")):
        raise MediaGenerationError("Motion Control requer URLs KIE acessíveis para a imagem e o vídeo enviados.")
    clean_prompt = str(prompt or "").strip()
    if len(clean_prompt) > 2500:
        raise MediaGenerationError("O prompt Motion Control não pode exceder 2500 caracteres.")
    base = _base_url(current) or "https://api.kie.ai/api/v1"
    body: dict[str, Any] = {
        "model": KIE_MOTION_MODEL,
        "input": {
            "prompt": clean_prompt or "Preserve a identidade visual da imagem de referência e aplique os movimentos do vídeo de forma natural, estável e fisicamente plausível.",
            "input_urls": [image_url],
            "video_urls": [video_url],
            "character_orientation": "video",
            "mode": "720p",
        },
    }

    def request(_: dict[str, Any]) -> Any:
        response = requests.post(f"{base}/jobs/createTask", headers=_headers(current), json=body, timeout=180)
        if response.status_code < 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            error = _kie_json_error(payload, fallback="A criação Motion Control KIE falhou.")
            if error:
                raise error
        return response

    try:
        routed = route_json_request(settings, pool=POOL_VIDEO, cards=[current], request=request)
        data = routed.payload.get("data") if isinstance(routed.payload.get("data"), Mapping) else {}
        task_id = str(data.get("taskId") or routed.payload.get("taskId") or "").strip()
        if not task_id:
            raise MediaGenerationError("KIE aceitou Motion Control mas não devolveu taskId.")
        urls = _poll_kie_task(routed.card, task_id, endpoint="/jobs/recordInfo", veo=False)
    except (ProviderRoutingError, ProviderCallError) as exc:
        raise MediaGenerationError(str(exc)) from exc
    destination = output_path or (STORAGE / "influencer_workflows" / f"motion-control-{task_id}.mp4")
    return _download_video_url(urls[0], destination, card=routed.card), task_id


def generate_ugc_segment(
    settings: Mapping[str, Any],
    card: Mapping[str, Any],
    *,
    image_url: str,
    prompt: str,
    output_path: Path,
    duration: int = 8,
) -> tuple[Path, str]:
    """Create one VEO3.1 image-to-video segment through the official KIE endpoint."""
    current = _require_kie_card(card)
    if not image_url.startswith(("http://", "https://")):
        raise MediaGenerationError("UGC Products requer um URL KIE acessível para a imagem do produto.")
    model = _model(current).lower() or "veo3_fast"
    if model not in KIE_VEO_MODELS:
        model = "veo3_fast"
    if duration not in {4, 6, 8}:
        raise MediaGenerationError("A duração de um segmento VEO3 deve ser 4, 6 ou 8 segundos.")
    base = _base_url(current) or "https://api.kie.ai/api/v1"
    body = {
        "prompt": str(prompt or "").strip(),
        "imageUrls": [image_url],
        "model": model,
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "duration": duration,
    }

    def request(_: dict[str, Any]) -> Any:
        response = requests.post(f"{base}/veo/generate", headers=_headers(current), json=body, timeout=180)
        if response.status_code < 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            error = _kie_json_error(payload, fallback="A criação de segmento VEO KIE falhou.")
            if error:
                raise error
        return response

    try:
        routed = route_json_request(settings, pool=POOL_VIDEO, cards=[current], request=request)
        data = routed.payload.get("data") if isinstance(routed.payload.get("data"), Mapping) else {}
        task_id = str(data.get("taskId") or routed.payload.get("taskId") or "").strip()
        if not task_id:
            raise MediaGenerationError("KIE aceitou VEO3 mas não devolveu taskId.")
        urls = _poll_kie_task(routed.card, task_id, endpoint="/veo/record-info", veo=True)
    except (ProviderRoutingError, ProviderCallError) as exc:
        raise MediaGenerationError(str(exc)) from exc
    return _download_video_url(urls[0], output_path, card=routed.card), task_id


def concatenate_video_files(paths: list[Path], output_path: Path) -> Path:
    """Join generated clips locally with FFmpeg, without uploading the result anywhere."""
    valid = [Path(path) for path in paths if Path(path).is_file()]
    if not valid:
        raise MediaGenerationError("Não existem segmentos locais para concatenar.")
    if len(valid) == 1:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if valid[0] != output_path:
            output_path.write_bytes(valid[0].read_bytes())
        return output_path
    try:
        from .metadata_cleaner import _resolve_ffmpeg

        ffmpeg = _resolve_ffmpeg()
    except Exception as exc:
        raise MediaGenerationError(str(exc)) from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, manifest_name = tempfile.mkstemp(prefix="ugc-concat-", suffix=".txt", dir=str(output_path.parent))
    os.close(descriptor)
    manifest = Path(manifest_name)
    try:
        manifest.write_text("\n".join(f"file '{str(path).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for path in valid) + "\n", encoding="utf-8")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c", "copy", str(output_path)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
        if completed.returncode != 0:
            raise MediaGenerationError(f"FFmpeg não conseguiu juntar os segmentos UGC: {completed.stderr[-500:]}")
    except OSError as exc:
        raise MediaGenerationError(f"Não foi possível executar FFmpeg para juntar os segmentos UGC: {exc}") from exc
    finally:
        manifest.unlink(missing_ok=True)
    return output_path


def generate_ugc_product_video(
    settings: Mapping[str, Any],
    card: Mapping[str, Any],
    *,
    image_url: str,
    prompts: list[str],
    duration: int = 8,
    output_path: Path | None = None,
) -> tuple[Path, list[str]]:
    """Generate two 8-second clips with the selected video card and concatenate them locally."""
    clean_prompts = [str(item or "").strip() for item in prompts if str(item or "").strip()]
    if len(clean_prompts) != 2:
        raise MediaGenerationError("UGC Products requer exactamente dois prompts de segmento.")
    ensure_storage()
    destination = output_path or (STORAGE / "influencer_workflows" / f"ugc-products-{abs(hash((image_url, *clean_prompts))) & 0xffffffffffffffff:x}.mp4")
    segment_paths = [destination.with_name(f"{destination.stem}-segment-{index + 1}.mp4") for index in range(2)]
    task_ids: list[str] = []
    for prompt, segment_path in zip(clean_prompts, segment_paths):
        generate_video_for_card(settings, card, prompt, image_url=image_url, duration=duration, aspect_ratio="9:16", output_path=segment_path)
        task_ids.append(segment_path.stem)
    return concatenate_video_files(segment_paths, destination), task_ids
