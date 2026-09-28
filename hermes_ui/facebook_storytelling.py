from __future__ import annotations

import json
import re
import shutil
import sqlite3
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont

from .creative_generation import CreativeGenerationError, _chat_json
from .media_generation import generate_image_from_pool, web_images_search
from .media_providers import media_cards_for_pool
from .storage import STORAGE, read_json

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "seed" / "references" / "facebook_posts_schema.sql"
DB_PATH = STORAGE / "state" / "facebook.db"
POSTS_JSON = STORAGE / "state" / "posts.json"
POSTS_LEGACY_JSON = STORAGE / "facebook_automation_posts.json"
POSTS_DIR = STORAGE / "facebook" / "posts"
VALID_STATUSES = {"tema_pendente", "para_producao", "artigo_pronto", "pronto_publicacao", "publicado", "erro"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_facebook_connection(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path or DB_PATH)
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema)
    return connection


def _decode_images(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        parsed = []
    return [dict(item) for item in parsed if isinstance(item, Mapping)] if isinstance(parsed, list) else []


def _row_to_post(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    post = dict(row)
    post["images"] = _decode_images(post.pop("imagens_json", post.pop("images_json", "[]")))
    aliases = {
        "channel_id": "channel_id", "tema": "theme", "tom": "tone", "titulo_gerado": "title",
        "artigo_text": "article_text", "quantidade_imagens": "image_count", "pasta_local": "folder",
        "link_publicado": "published_url",
    }
    for source, target in aliases.items():
        if source in post:
            post[target] = post[source]
    post["id"] = str(post.get("id") or "")
    return post


def get_used_themes_for_channel(channel_id: str, limit: int = 200) -> list[str]:
    with get_facebook_connection() as conn:
        rows = conn.execute(
            """SELECT tema FROM facebook_posts
               WHERE channel_id = ? AND status NOT IN ('erro', 'cancelado')
               ORDER BY created_at DESC LIMIT ?""",
            (str(channel_id), max(1, int(limit))),
        ).fetchall()
    return [str(row[0]) for row in rows if str(row[0] or "").strip()]


def _upsert_images(conn: sqlite3.Connection, post_id: str, images: list[Mapping[str, Any]]) -> None:
    conn.execute("DELETE FROM facebook_post_images WHERE post_id = ?", (post_id,))
    for fallback_index, item in enumerate(images, start=1):
        conn.execute(
            """INSERT INTO facebook_post_images
               (post_id, image_index, search_query, overlay_text, image_path, image_final_path, provider, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                post_id,
                int(item.get("index") or fallback_index),
                str(item.get("search_query") or ""),
                str(item.get("overlay_text") or ""),
                str(item.get("image_path") or item.get("path") or ""),
                str(item.get("image_final_path") or item.get("final_path") or item.get("captioned_path") or ""),
                str(item.get("provider") or item.get("source") or ""),
                str(item.get("status") or "pending"),
            ),
        )


def save_facebook_post(post: Mapping[str, Any], *, db_path: str | Path | None = None) -> dict[str, Any]:
    value = dict(post)
    post_id = str(value.get("id") or f"fbpost_{uuid.uuid4().hex[:12]}")
    channel_id = str(value.get("channel_id") or value.get("page_id") or "")
    images = _decode_images(value.get("images") or value.get("imagens_json"))
    folder = str(value.get("folder") or value.get("pasta_local") or (POSTS_DIR / post_id))
    status = str(value.get("status") or "tema_pendente")
    if status not in VALID_STATUSES:
        status = "erro"
    now = _now()
    with get_facebook_connection(db_path) as conn:
        existing = conn.execute("SELECT created_at FROM facebook_posts WHERE id = ?", (post_id,)).fetchone()
        created_at = str(value.get("created_at") or (existing[0] if existing else now))
        conn.execute(
            """INSERT INTO facebook_posts
               (id, channel_id, tema, tom, titulo_gerado, artigo_text, slug,
                quantidade_imagens, status, pasta_local, link_publicado, imagens_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET channel_id=excluded.channel_id, tema=excluded.tema,
                tom=excluded.tom, titulo_gerado=excluded.titulo_gerado, artigo_text=excluded.artigo_text,
                slug=excluded.slug, quantidade_imagens=excluded.quantidade_imagens, status=excluded.status,
                pasta_local=excluded.pasta_local, link_publicado=excluded.link_publicado,
                imagens_json=excluded.imagens_json, updated_at=excluded.updated_at""",
            (
                post_id, channel_id, str(value.get("theme") or value.get("tema") or ""),
                str(value.get("tone") or value.get("tom") or ""), str(value.get("title") or value.get("titulo_gerado") or ""),
                str(value.get("article_text") or value.get("artigo_text") or ""), str(value.get("slug") or post_id),
                max(1, min(5, int(value.get("image_count") or value.get("quantidade_imagens") or len(images) or 5))),
                status, folder, str(value.get("published_url") or value.get("link_publicado") or ""),
                json.dumps(images, ensure_ascii=False), created_at, now,
            ),
        )
        _upsert_images(conn, post_id, images)
        row = conn.execute("SELECT * FROM facebook_posts WHERE id = ?", (post_id,)).fetchone()
    return _row_to_post(row)


def list_facebook_posts(channel_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    clauses, params = [], []
    if channel_id:
        clauses.append("channel_id = ?")
        params.append(str(channel_id))
    if status:
        clauses.append("status = ?")
        params.append(str(status))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_facebook_connection() as conn:
        rows = conn.execute(f"SELECT * FROM facebook_posts{where} ORDER BY created_at DESC", params).fetchall()
    return [_row_to_post(row) for row in rows]


def get_facebook_post(post_id: str) -> dict[str, Any] | None:
    with get_facebook_connection() as conn:
        row = conn.execute("SELECT * FROM facebook_posts WHERE id = ?", (str(post_id),)).fetchone()
    return _row_to_post(row) if row else None


def update_facebook_post_status(post_id: str, status: str, **fields: Any) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Estado Facebook inválido: {status}")
    current = get_facebook_post(post_id)
    if current is None:
        raise KeyError(f"Post Facebook não encontrado: {post_id}")
    return save_facebook_post({**current, **fields, "id": post_id, "status": status})


def _theme_prompt(used: list[str]) -> str:
    return """Você é um curador de temas para uma página de storytelling viral no estilo 'Update Diário' (biografias de superação, curiosidades históricas, histórias de empresários, atletas e cientistas com reviravoltas).
Escolha UM tema novo, específico e visualmente forte. Não repita os temas já usados neste canal nem histórias muito parecidas. Alterne entre empresários, atletas, cientistas, artistas, inventores, factos históricos e superação pessoal. Evite biografar pessoas vivas em temas delicados ou controversos.
Temas já usados neste canal:
%s
Retorne SOMENTE JSON com as chaves tema e tom. O tom deve ser exactamente um de: Motivacional/Superação, Curiosidade Histórica, Biografia de Empresário.""" % json.dumps(used, ensure_ascii=False)


def generate_storytelling_theme(settings: dict[str, Any], channel: Mapping[str, Any]) -> dict[str, Any]:
    channel_id = str(channel.get("id") or channel.get("channel_id") or "")
    result = _chat_json(settings, _theme_prompt(get_used_themes_for_channel(channel_id)), json.dumps({"channel": dict(channel)}, ensure_ascii=False))
    theme = str(result.get("tema") or result.get("theme") or "").strip()
    tone = str(result.get("tom") or result.get("tone") or "Motivacional/Superação").strip()
    if not theme:
        raise CreativeGenerationError("O LLM não devolveu um tema válido para a Facebook Page.")
    return {"channel_id": channel_id, "theme": theme, "tone": tone, "status": "para_producao"}


def generate_storytelling_article(settings: dict[str, Any], channel: Mapping[str, Any], tema: str, tom: str, quantidade_imagens: int) -> dict[str, Any]:
    count = max(1, min(5, int(quantidade_imagens)))
    system = f"""Você é um roteirista de posts virais de storytelling em português, no estilo de páginas como Update Diário. Gere um artigo completo sobre o tema fornecido, com frases curtas, uma ideia por linha, quebras dramáticas frequentes, contexto de ano/lugar, factos e números concretos, obstáculos, reviravoltas e uma frase final de efeito. Não invente factos sobre pessoas reais; se o tema não especificar pessoa real, crie uma história genérica plausível e não a atribua a alguém real. Gere exactamente {count} cards de imagem em ordem cronológica. Cada card deve conter search_query objectivo para uma FOTO REAL e overlay_text com no máximo 25 palavras. Retorne SOMENTE JSON com title, article_text e images."""
    result = _chat_json(settings, system, json.dumps({"channel": dict(channel), "tema": tema, "tom": tom, "quantidade_imagens": count}, ensure_ascii=False))
    article = str(result.get("article_text") or result.get("article") or "").strip()
    title = str(result.get("title") or tema or "Post Facebook").strip()
    raw_images = result.get("images") if isinstance(result.get("images"), list) else []
    images = []
    for index, item in enumerate(raw_images[:count], start=1):
        if isinstance(item, Mapping):
            images.append({"index": index, "search_query": str(item.get("search_query") or "").strip(), "overlay_text": str(item.get("overlay_text") or "").strip(), "status": "pending"})
    if not article or len(images) != count or any(not item["search_query"] or not item["overlay_text"] for item in images):
        raise CreativeGenerationError("O LLM devolveu um artigo ou cards de imagem incompletos.")
    return {"title": title, "article_text": article, "images": images, "image_count": count}


def _download(url: str, destination: Path) -> Path:
    import requests
    response = requests.get(url, timeout=45, headers={"User-Agent": "Thunderbolt Facebook Storytelling/1.0"})
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return destination


def collect_storytelling_images(settings: Mapping[str, Any], post: Mapping[str, Any], *, source: str = "web") -> dict[str, Any]:
    source = "ai" if str(source).lower() in {"ai", "imagem e video ia", "image_ai"} else "web"
    folder = Path(str(post.get("folder") or POSTS_DIR / str(post.get("id"))) )
    folder.mkdir(parents=True, exist_ok=True)
    images = []
    for index, item in enumerate(_decode_images(post.get("images")), start=1):
        record = dict(item)
        query = str(record.get("search_query") or post.get("theme") or "").strip()
        try:
            if source == "web":
                result = web_images_search(settings, query, num_results=1, rights="sur:cl")[0]
                path = _download(str(result.get("url") or result.get("link") or ""), folder / f"image-{index}.jpg")
                provider = str(result.get("source") or "web")
            else:
                path = generate_image_from_pool(settings, query, topic=str(post.get("theme") or ""), variant_index=index, aspect_ratio="1:1")
                target = folder / f"image-{index}.png"
                if Path(path).resolve() != target.resolve():
                    shutil.copy2(path, target)
                path = target
                provider = "image_ai"
            record.update({"index": index, "image_path": str(path), "path": str(path), "provider": provider, "status": "downloaded"})
        except Exception as exc:
            record.update({"index": index, "provider": source, "status": "skipped", "error": str(exc)[:300]})
        images.append(record)
    downloaded = sum(1 for item in images if item.get("image_path"))
    status = "artigo_pronto" if downloaded else "erro"
    return save_facebook_post({**post, "images": images, "status": status})


def _font(font_path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path.is_file():
        return ImageFont.truetype(str(font_path), size)
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def apply_overlay_with_pillow(image_path: Path, overlay_text: str, font_path: Path, font_size: int = 60, position: str = "top_center") -> Path:
    image_path = Path(image_path)
    with Image.open(image_path).convert("RGB") as image:
        draw = ImageDraw.Draw(image)
        font = _font(Path(font_path), max(12, int(font_size)))
        max_width = max(1, int(image.width * 0.8))
        words = str(overlay_text or "").split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        lines = lines or [""]
        spacing = max(4, int(font_size * 0.18))
        line_heights = [draw.textbbox((0, 0), line, font=font)[3] for line in lines]
        block_height = sum(line_heights) + spacing * (len(lines) - 1)
        if position == "center":
            start_y = (image.height - block_height) // 2
        elif position == "bottom_center":
            start_y = image.height - block_height - max(24, int(font_size * 0.6))
        else:
            start_y = max(24, int(font_size * 0.6))
        y = max(0, start_y)
        for line, height in zip(lines, line_heights):
            bbox = draw.textbbox((0, 0), line, font=font)
            x = (image.width - (bbox[2] - bbox[0])) // 2
            draw.text((x, y), line, font=font, fill="white", stroke_width=3, stroke_fill="black")
            y += height + spacing
        match = re.search(r"(?:image|final|captioned)[-_]?(\d+)", image_path.stem, re.IGNORECASE)
        index = match.group(1) if match else "1"
        output = image_path.parent / f"final_{index}.png"
        image.save(output, "PNG")
    return output


def caption_storytelling_images(settings: Mapping[str, Any], post: Mapping[str, Any]) -> dict[str, Any]:
    font = Path(str(settings.get("facebook_overlay_font") or "Montserrat-Bold.ttf"))
    if not font.is_absolute():
        font = ROOT / font
    size = int(settings.get("facebook_overlay_font_size") or 60)
    position = str(settings.get("facebook_overlay_position") or "top_center")
    updated, success = [], 0
    for item in _decode_images(post.get("images")):
        record = dict(item)
        path = Path(str(record.get("image_path") or record.get("path") or ""))
        try:
            if not path.is_file():
                raise FileNotFoundError(path)
            final = apply_overlay_with_pillow(path, str(record.get("overlay_text") or ""), font, size, position)
            record.update({"image_final_path": str(final), "final_path": str(final), "captioned_path": str(final), "status": "processed"})
            success += 1
        except Exception as exc:
            record.update({"status": "skipped", "error": str(exc)[:300]})
        updated.append(record)
    required = min(3, max(1, int(post.get("image_count") or len(updated) or 1)))
    return save_facebook_post({**post, "images": updated, "status": "pronto_publicacao" if success >= required else "erro"})


def migrate_posts_json_to_sqlite() -> int:
    candidates = (POSTS_JSON, STORAGE / "posts.json", POSTS_LEGACY_JSON, STORAGE / "state" / "facebook_automation_posts.json")
    if any(path.with_name(path.name + ".migrated").is_file() for path in candidates):
        return 0
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        return 0
    migrated = source.with_name(source.name + ".migrated")
    if migrated.exists():
        return 0
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    entries = payload if isinstance(payload, list) else []
    count = 0
    for item in entries:
        if isinstance(item, Mapping):
            save_facebook_post(item)
            count += 1
    try:
        source.rename(migrated)
    except OSError:
        pass
    return count


__all__ = [
    "DB_PATH", "POSTS_DIR", "apply_overlay_with_pillow", "caption_storytelling_images",
    "collect_storytelling_images", "generate_storytelling_article", "generate_storytelling_theme",
    "get_facebook_connection", "get_facebook_post", "get_used_themes_for_channel",
    "list_facebook_posts", "migrate_posts_json_to_sqlite", "save_facebook_post", "update_facebook_post_status",
]
