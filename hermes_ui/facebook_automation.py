from __future__ import annotations

import json
import re
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests
from PIL import Image, ImageDraw, ImageFont

from .creative_generation import CreativeGenerationError, _chat_json
from .media_generation import GOOGLE_IMAGES_COPYRIGHT_WARNING, generate_image_for_card, google_images_search
from .storage import STORAGE, read_json, write_json

POSTS_FILE = "facebook_automation_posts.json"
POSTS_DIR = STORAGE / "facebook_automation"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _posts() -> list[dict[str, Any]]:
    value = read_json(POSTS_FILE, [])
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def list_posts() -> list[dict[str, Any]]:
    return sorted(_posts(), key=lambda item: str(item.get("created_at") or ""), reverse=True)


def save_post(post: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(post)
    value.setdefault("id", f"fbpost_{uuid.uuid4().hex[:12]}")
    value.setdefault("created_at", _now())
    entries = _posts()
    for index, existing in enumerate(entries):
        if str(existing.get("id")) == str(value["id"]):
            entries[index] = value
            break
    else:
        entries.append(value)
    write_json(POSTS_FILE, entries)
    return value


def create_post(page: Mapping[str, Any], *, image_count: int = 3, theme: str = "") -> dict[str, Any]:
    post_id = f"fbpost_{uuid.uuid4().hex[:12]}"
    folder = POSTS_DIR / post_id / "images"
    folder.mkdir(parents=True, exist_ok=True)
    return save_post({
        "id": post_id,
        "page_id": str(page.get("id") or ""),
        "page_name": str(page.get("name") or "Facebook Page"),
        "page_url": str(page.get("url") or ""),
        "theme": theme.strip(),
        "tone": "Motivacional/Superação",
        "image_count": max(1, min(5, int(image_count))),
        "status": "tema_pendente",
        "created_at": _now(),
        "folder": str(folder),
        "images": [],
    })


def generate_theme(settings: dict[str, Any], post: Mapping[str, Any], page: Mapping[str, Any], context: str = "") -> dict[str, Any]:
    system = (
        "És um curador de temas para posts virais de storytelling em português para uma Facebook Page. "
        "Escolhe um tema específico, novo e visualmente forte, com contexto, obstáculo e reviravolta. "
        "Não inventes factos sobre pessoas reais; quando não houver pessoa indicada, cria uma história genérica plausível. "
        "Responde apenas JSON válido com as chaves tema e tom."
    )
    result = _chat_json(settings, system, json.dumps({
        "page": {"name": page.get("name"), "description": page.get("description"), "niche": page.get("niche"), "country": page.get("country")},
        "context": context or post.get("theme") or "",
        "tone_options": ["Motivacional/Superação", "Curiosidade Histórica", "Biografia de Empresário"],
    }, ensure_ascii=False))
    theme = str(result.get("tema") or result.get("theme") or "").strip()
    tone = str(result.get("tom") or result.get("tone") or "Motivacional/Superação").strip()
    if not theme:
        raise CreativeGenerationError("O LLM não devolveu um tema válido para a página Facebook.")
    return save_post({**post, "theme": theme, "tone": tone, "status": "artigo_pendente"})


def generate_article(settings: dict[str, Any], post: Mapping[str, Any], page: Mapping[str, Any]) -> dict[str, Any]:
    image_count = max(1, min(5, int(post.get("image_count") or 3)))
    system = (
        "És um roteirista de posts virais de storytelling para Facebook, em português. "
        "Gera um artigo completo com aproximadamente 650 a 900 palavras, semelhante ao formato de storytelling do exemplo: "
        "frases curtas, uma ideia por linha, quebras frequentes, contexto de ano/lugar, factos e números concretos, "
        "obstáculos, reviravoltas e uma frase final de efeito. Não inventes factos sobre pessoas reais. "
        f"Depois do artigo, gera exatamente {image_count} cards em ordem cronológica. Cada card deve conter "
        "index, search_query e overlay_text com no máximo 25 palavras. Responde apenas JSON válido com title, article_text e images."
    )
    result = _chat_json(settings, system, json.dumps({
        "page": {"name": page.get("name"), "description": page.get("description"), "niche": page.get("niche"), "country": page.get("country")},
        "theme": post.get("theme"), "tone": post.get("tone"), "image_count": image_count,
        "requirements": {"approximate_words": "650-900", "language": "pt-BR", "format": "one idea per line"},
    }, ensure_ascii=False))
    article = str(result.get("article_text") or result.get("article") or "").strip()
    title = str(result.get("title") or post.get("theme") or "Post Facebook").strip()
    images = result.get("images") if isinstance(result.get("images"), list) else []
    normalized_images = []
    for index, item in enumerate(images[:image_count], start=1):
        if isinstance(item, Mapping):
            normalized_images.append({"index": index, "search_query": str(item.get("search_query") or "").strip(), "overlay_text": str(item.get("overlay_text") or "").strip()})
    if not article or not normalized_images:
        raise CreativeGenerationError("O LLM devolveu um artigo ou cards de imagem incompletos.")
    return save_post({**post, "title": title, "article_text": article, "images": normalized_images, "status": "imagens_pendentes"})


def _download_image(url: str, destination: Path) -> Path:
    response = requests.get(url, timeout=45, headers={"User-Agent": "Thunderbolt Facebook Automation/1.0"})
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def collect_images(settings: dict[str, Any], post: Mapping[str, Any], *, source: str = "google") -> dict[str, Any]:
    """Collect Facebook visuals exclusively from Google Images (commercial celebrity use is legally risky)."""
    folder = Path(str(post.get("folder") or (POSTS_DIR / str(post.get("id"))))) / "images"
    if not any(google_images_searchable for google_images_searchable in [True] if isinstance(settings.get("google_images_cards"), list) and settings.get("google_images_cards")):
        raise ValueError("Configure pelo menos um cartão Google Images antes de recolher imagens para Facebook Pages.")
    images = []
    for index, item in enumerate(post.get("images") or [], start=1):
        query = str(item.get("search_query") or post.get("theme") or "").strip()
        image_record = dict(item)
        try:
            results = google_images_search(settings, query, num_results=1, safe="active")
            link = str((results[0] if results else {}).get("link") or "")
            if not link:
                raise ValueError("A pesquisa Google não devolveu uma imagem.")
            destination = folder / f"image-{index}.jpg"
            _download_image(link, destination)
            image_record.update({"source": "google_images", "path": str(destination), "status": "imagem_baixada"})
        except Exception as exc:
            image_record.update({"source": "google_images", "status": "erro", "error": str(exc)[:300]})
        images.append(image_record)
    return save_post({**post, "images": images, "status": "legendas_pendentes" if any(item.get("path") for item in images) else "imagens_pendentes"})


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def caption_images(post: Mapping[str, Any]) -> dict[str, Any]:
    updated = []
    for index, item in enumerate(post.get("images") or [], start=1):
        record = dict(item)
        raw_path = str(record.get("path") or "")
        if raw_path and Path(raw_path).is_file():
            source = Path(raw_path)
            output = source.with_name(f"captioned-{source.stem}.jpg")
            with Image.open(source).convert("RGB") as image:
                image.thumbnail((1600, 1600))
                canvas = Image.new("RGB", image.size, "black")
                canvas.paste(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2))
                draw = ImageDraw.Draw(canvas)
                text = str(record.get("overlay_text") or "").strip()
                font = _font(max(28, min(64, canvas.width // 22)))
                lines = textwrap.wrap(text, width=max(18, canvas.width // 32))
                line_height = int(font.size * 1.2) if hasattr(font, "size") else 40
                box_height = line_height * len(lines) + 48
                y = canvas.height - box_height - 24
                draw.rounded_rectangle((24, y, canvas.width - 24, canvas.height - 24), radius=18, fill=(0, 0, 0, 190))
                for line in lines:
                    bbox = draw.textbbox((0, 0), line, font=font)
                    x = (canvas.width - (bbox[2] - bbox[0])) // 2
                    draw.text((x + 2, y + 16), line, font=font, fill="black")
                    draw.text((x, y + 14), line, font=font, fill="white")
                    y += line_height
                canvas.save(output, "JPEG", quality=92)
            record["captioned_path"] = str(output)
            record["status"] = "legendada"
        updated.append(record)
    return save_post({**post, "images": updated, "status": "pronto_upload" if any(item.get("captioned_path") for item in updated) else "legendas_pendentes"})


def publish_to_facebook(post: Mapping[str, Any], page: Mapping[str, Any]) -> dict[str, Any]:
    page_id = str(page.get("page_id") or page.get("facebook_page_id") or "").strip()
    token = str(page.get("access_token") or page.get("facebook_access_token") or "").strip()
    if not page_id or not token:
        raise ValueError("Configure o Page ID e o Access Token da Meta nesta página Facebook antes de publicar.")
    message = f"{post.get('title') or post.get('theme') or ''}\n\n{post.get('article_text') or ''}".strip()
    published = []
    for item in post.get("images") or []:
        path = Path(str(item.get("captioned_path") or item.get("path") or ""))
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            response = requests.post(f"https://graph.facebook.com/v20.0/{page_id}/photos", data={"caption": message, "published": "false", "access_token": token}, files={"source": (path.name, handle, "image/jpeg")}, timeout=90)
        payload = response.json() if response.content else {}
        if response.status_code >= 400 or payload.get("error"):
            raise ValueError(str(payload.get("error", {}).get("message") or f"Meta Graph API HTTP {response.status_code}"))
        published.append(payload)
    if not published:
        raise ValueError("Não existe nenhuma imagem legendada para publicar.")
    return save_post({**post, "status": "publicado", "published_at": _now(), "facebook_media_ids": published})


__all__ = ["POSTS_DIR", "caption_images", "collect_images", "create_post", "generate_article", "generate_theme", "list_posts", "publish_to_facebook", "save_post"]
