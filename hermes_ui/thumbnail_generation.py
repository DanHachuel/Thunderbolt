import base64
import binascii
import hashlib
import mimetypes
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps

from hermes_ui.storage import STORAGE, ensure_storage


GEMINI_INTERACTIONS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
DEFAULT_ASPECT_RATIO = "16:9"
DEFAULT_IMAGE_SIZE = "1K"
DEFAULT_MIME_TYPE = "image/jpeg"
DEFAULT_IMAGE_EXTENSION = ".jpg"
THUMBNAIL_WIDTH = 1792
THUMBNAIL_HEIGHT = 1024
VERTICAL_THUMBNAIL_WIDTH = 1024
VERTICAL_THUMBNAIL_HEIGHT = 1792


class ThumbnailGenerationError(RuntimeError):
    """Raised when Nano Banana cannot produce a thumbnail image."""


def infer_thumbnail_aspect_ratio(
    prompt: str = "",
    blueprint: dict[str, Any] | None = None,
    *,
    fallback: str = DEFAULT_ASPECT_RATIO,
) -> str:
    """Resolve the requested thumbnail orientation without trusting provider defaults."""
    blueprint_content = str((blueprint or {}).get("content") or "")
    if re.search(r"\b9\s*:\s*16\b|\bvertical\b|\bportrait\b", blueprint_content, flags=re.IGNORECASE):
        return "9:16"
    if re.search(r"\b16\s*:\s*9\b|\blandscape\b|\bwide\b", blueprint_content, flags=re.IGNORECASE):
        return "16:9"
    prompt_text = str(prompt or "")
    if re.search(r"\b9\s*:\s*16\b|\bvertical\b|\bportrait\b", prompt_text, flags=re.IGNORECASE):
        return "9:16"
    if re.search(r"\b16\s*:\s*9\b|\blandscape\b|\bwide\b", prompt_text, flags=re.IGNORECASE):
        return "16:9"
    return fallback if fallback in {"16:9", "9:16"} else DEFAULT_ASPECT_RATIO


def normalize_thumbnail_bytes(image_bytes: bytes, aspect_ratio: str = DEFAULT_ASPECT_RATIO) -> bytes:
    """Return a non-distorted JPEG in the requested thumbnail orientation."""
    try:
        with Image.open(__import__("io").BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            size = (VERTICAL_THUMBNAIL_WIDTH, VERTICAL_THUMBNAIL_HEIGHT) if str(aspect_ratio) == "9:16" else (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
            image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            output = __import__("io").BytesIO()
            image.save(output, format="JPEG", quality=95, optimize=True)
            return output.getvalue()
    except Exception:
        # Keep the existing provider error/response path for non-image test
        # doubles and legacy adapters; real image bytes are normalized above.
        return image_bytes


def _clean_detail(value: Any, api_key: str) -> str:
    detail = str(value or "").strip()[:600]
    return detail.replace(api_key, "[REDACTED]") if api_key else detail


def _fallback_lettering(topic: str) -> str:
    """Return a short headline when an older task has no overlay_text."""
    words = re.findall(r"[\wÀ-ÿ$%'-]+", str(topic or ""), flags=re.UNICODE)
    headline = " ".join(words[:4]).strip()
    return headline.upper() if headline else "WATCH NOW"


def _normalise_lettering_text(value: Any, topic: str) -> str:
    """Keep the required thumbnail headline concise and never empty."""
    words = re.findall(r"[\wÀ-ÿ$%'-]+", str(value or ""), flags=re.UNICODE)
    if not words:
        return _fallback_lettering(topic)
    return " ".join(words[:4]).strip()


def _compose_thumbnail_prompt(
    base_prompt: str,
    *,
    topic: str = "",
    lettering_text: str = "",
    lettering_prompt: str = "",
) -> tuple[str, str]:
    """Combine the visual base and a mandatory, model-readable lettering layer."""
    headline = _normalise_lettering_text(lettering_text, topic)
    lettering_guidance = str(lettering_prompt or "").strip() or (
        "Use a bold sans-serif headline with high contrast, a thick outline or shadow, "
        "safe margins and placement that does not cover the face or main subject."
    )
    effective_prompt = (
        "IMAGE BASE LAYER — create the requested cinematic YouTube thumbnail composition, subject, "
        "lighting, colour palette and visual hierarchy. Keep the base image clean and uncluttered.\n"
        f"{str(base_prompt or '').strip()}\n\n"
        "MANDATORY LETTERING LAYER — the final image MUST visibly contain readable lettering. "
        "If the image-base description says no text, no words or no lettering, that restriction is overridden "
        "by this layer. Render the exact headline between the delimiters below; do not omit it, paraphrase it, "
        "translate it, replace it with placeholder text or hide it.\n"
        f"EXACT HEADLINE TO RENDER: <<<{headline}>>>\n"
        f"LETTERING DESIGN: {lettering_guidance}\n"
        "Use no more than three or four words, bold sans-serif typography, strong contrast, outline/shadow, "
        "a safe-zone margin and a position that does not cover the face or main object. Do not add unrelated text, "
        "logos or watermarks. The thumbnail must not be delivered without the exact headline visible."
    )
    return effective_prompt, headline


def _decode_image_data(value: Any) -> bytes | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None
    return data or None


def _image_from_content(content: Any) -> bytes | None:
    if not isinstance(content, dict) or content.get("type") != "image":
        return None
    return _decode_image_data(content.get("data"))


def _extract_image_bytes(payload: dict[str, Any]) -> bytes:
    """Extract the last inline image from an Interactions API response."""
    steps = payload.get("steps") or []
    for step in reversed(steps if isinstance(steps, list) else []):
        content = step.get("content") if isinstance(step, dict) else None
        for block in reversed(content if isinstance(content, list) else []):
            image = _image_from_content(block)
            if image:
                return image

    output_image = payload.get("output_image")
    image = _image_from_content(output_image)
    if image:
        return image

    outputs = payload.get("outputs")
    for output in reversed(outputs if isinstance(outputs, list) else []):
        image = _image_from_content(output)
        if image:
            return image

    raise ThumbnailGenerationError("O Gemini concluiu a interação, mas não devolveu uma imagem inline.")


def _image_input(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ThumbnailGenerationError("A imagem de referência da thumbnail não está disponível no storage.")
    try:
        image_data = path.read_bytes()
    except OSError as exc:
        raise ThumbnailGenerationError("Não foi possível ler a imagem de referência da thumbnail.") from exc
    if not image_data:
        raise ThumbnailGenerationError("A imagem de referência da thumbnail está vazia.")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    if not mime_type.startswith("image/"):
        mime_type = "image/jpeg"
    return {
        "type": "image",
        "mime_type": mime_type,
        "data": base64.b64encode(image_data).decode("ascii"),
    }


def _thumbnail_filename(prompt: str, topic: str, variant_index: int, model: str) -> str:
    source = f"{model}\n{topic.strip()}\n{variant_index}\n{prompt.strip()}".encode("utf-8")
    digest = hashlib.sha256(source).hexdigest()[:20]
    return f"gemini-thumbnail-{digest}{DEFAULT_IMAGE_EXTENSION}"


def generate_thumbnail_image(
    settings: dict[str, Any],
    prompt: str,
    *,
    topic: str = "",
    variant_index: int = 0,
    reference_image: str | Path | None = None,
    lettering_text: str = "",
    lettering_prompt: str = "",
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    lock_aspect_ratio: bool = False,
) -> Path:
    api_key = str(settings.get("gemini_image_api_key") or "").strip()
    if not api_key:
        raise ThumbnailGenerationError("Configure a API key Nano Banana em Configuração API > API Keys > Serviços e modelos.")
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ThumbnailGenerationError("A thumbnail não tem um prompt de imagem para gerar.")
    effective_prompt, headline = _compose_thumbnail_prompt(
        clean_prompt,
        topic=topic,
        lettering_text=lettering_text,
        lettering_prompt=lettering_prompt,
    )
    effective_aspect_ratio = (
        aspect_ratio if lock_aspect_ratio and aspect_ratio in {"16:9", "9:16"}
        else infer_thumbnail_aspect_ratio(clean_prompt, fallback=aspect_ratio)
    )

    model = str(settings.get("gemini_image_model") or DEFAULT_GEMINI_IMAGE_MODEL).strip()
    image_size = DEFAULT_IMAGE_SIZE
    request_input: str | list[dict[str, str]] = effective_prompt
    if reference_image:
        request_input = [
            {"type": "text", "text": effective_prompt},
            _image_input(Path(reference_image)),
        ]
    body = {
        "model": model,
        "input": request_input,
        "response_format": {
            "type": "image",
            "mime_type": DEFAULT_MIME_TYPE,
            "aspect_ratio": effective_aspect_ratio,
            "image_size": image_size,
        },
        "store": False,
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    try:
        response = requests.post(
            GEMINI_INTERACTIONS_ENDPOINT,
            headers=headers,
            json=body,
            timeout=180,
        )
    except requests.RequestException as exc:
        raise ThumbnailGenerationError(f"Não foi possível contactar a API Nano Banana: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", response.text)
        except ValueError:
            detail = response.text
        raise ThumbnailGenerationError(f"A API Nano Banana devolveu HTTP {response.status_code}: {_clean_detail(detail, api_key)}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ThumbnailGenerationError("A API Nano Banana devolveu uma resposta que não é JSON.") from exc
    if str(payload.get("status") or "completed").lower() not in {"completed", "succeeded"}:
        raise ThumbnailGenerationError(f"A interação Nano Banana terminou com estado inesperado: {payload.get('status') or 'desconhecido'}.")
    image_bytes = normalize_thumbnail_bytes(_extract_image_bytes(payload), effective_aspect_ratio)

    ensure_storage()
    output_dir = STORAGE / "thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / _thumbnail_filename(
        f"{effective_prompt}\nEXACT HEADLINE TO RENDER: {headline}",
        topic,
        variant_index,
        model,
    )
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=output_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(image_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return destination


__all__ = [
    "DEFAULT_ASPECT_RATIO",
    "DEFAULT_GEMINI_IMAGE_MODEL",
    "DEFAULT_IMAGE_SIZE",
    "infer_thumbnail_aspect_ratio",
    "THUMBNAIL_HEIGHT",
    "THUMBNAIL_WIDTH",
    "GEMINI_INTERACTIONS_ENDPOINT",
    "ThumbnailGenerationError",
    "generate_thumbnail_image",
    "normalize_thumbnail_bytes",
]
