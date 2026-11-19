from __future__ import annotations

from pathlib import Path
from typing import Any

from .creative_generation import CreativeGenerationError, generate_thumbnail_prompt
from .media_generation import MediaGenerationError, generate_image_from_pool
from .only_music import resolve_music_source
from .text_to_images import assemble_text_to_images_video
from .thumbnail_blueprints import music_thumbnail_blueprint_for_task


# Substitui o placeholder "Clipes de Música". Pipeline completo de um clip:
#   1. LLM gera o prompt da imagem de fundo (SEM texto) + o headline, seguindo as
#      regras do Music Thumbnail Blueprint seleccionado ( thumbnail_blueprint_rules).
#   2. O pool de imagem (Nano Banana/FAL) gera o fundo SEM texto.
#   3. O headline é aplicado por cima (PIL) com a tipografia do blueprint
#      (Bebas Neue/Impact/Montserrat, branco, outline escuro, 2 linhas, terço
#      inferior) — NUNCA na IA de imagem, como os blueprints exigem.
#   4. A imagem queimada vira o clip (still sobre a duração do áudio) e é feito o
#      mux com a música.

# Fontes candidatas para a tipografia agressiva dos blueprints (a primeira que
# existir ganha). O headline fica sempre legível mesmo sem nenhuma delas.
_HEADLINE_FONT_CANDIDATES = ("BebasNeue-Regular.ttf", "bebasneue.ttf", "BebasNeue.ttf", "impact.ttf", "IMPACT.TTF", "arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf")
_FONT_DIRS = (
    Path("C:/Windows/Fonts"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts"),
    Path("/Library/Fonts"),
)


def _headline_lines(overlay: str) -> list[str]:
    """Divide o headline em até 2 linhas — gancho (3-5 palavras) + contexto (2-4)."""
    words = " ".join(str(overlay or "").split()).split()
    if not words:
        return []
    if len(words) <= 5:
        return [" ".join(words)]
    return [" ".join(words[:5]), " ".join(words[5:9])]


def _resolve_headline_font(size: int):
    from PIL import ImageFont

    for candidate in _HEADLINE_FONT_CANDIDATES:
        for base in _FONT_DIRS:
            path = base / candidate
            try:
                if path.is_file():
                    return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def apply_music_text_overlay(image_path: Path | str, headline: str) -> Path:
    """Queima o headline por cima da imagem de fundo (PIL) — sem tocar na IA.

    Segue a lei comum dos dois blueprints: até 2 linhas, fonte de display
    agressiva, branco com outline escuro, terço inferior/centro, legível no
    celular. Sem headline, devolve a imagem original.
    """
    source = Path(str(image_path))
    lines = _headline_lines(headline)
    if not lines or not source.is_file():
        return source
    from PIL import Image, ImageDraw

    image = Image.open(source).convert("RGB")
    width, height = image.size
    font_size = max(28, int(height * 0.12))
    font = _resolve_headline_font(font_size)
    draw = ImageDraw.Draw(image)
    stroke = max(2, int(font_size * 0.06))
    line_gap = int(font_size * 0.22)
    line_boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke) for line in lines]
    line_heights = [box[3] - box[1] for box in line_boxes]
    block_height = sum(line_heights) + line_gap * (len(lines) - 1)
    # Terço inferior/centro, como rege a composição dos blueprints.
    top = max(int(height * 0.12), int(height - block_height - height * 0.12))
    y = top
    for index, line in enumerate(lines):
        box = line_boxes[index]
        text_width = box[2] - box[0]
        x = max(stroke, (width - text_width) // 2 - box[0])
        draw.text(
            (x, y - box[1]),
            line,
            font=font,
            fill="white",
            stroke_width=stroke,
            stroke_fill=(10, 10, 10),
        )
        y += line_heights[index] + line_gap
    output = source.with_name(f"{source.stem}-texto.jpg")
    image.save(output, "JPEG", quality=92)
    return output


def generate_music_clip_frame(task: dict[str, Any], settings: dict[str, Any], channel: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Gera o fotograma final do clip (fundo sem texto + headline queimado)."""
    blueprint = music_thumbnail_blueprint_for_task(channel, task)
    if not str(blueprint.get("content") or "").strip():
        raise CreativeGenerationError("Clipes de Música exige um Music Thumbnail Blueprint selecionado.")
    topic = str(task.get("topic") or task.get("title") or "Música").strip()
    variant = generate_thumbnail_prompt(
        settings,
        channel,
        topic,
        # As regras do Music Thumbnail Blueprint entram no prompt como
        # thumbnail_blueprint_rules (mesmo mecanismo dos thumbnails de vídeo).
        blueprint={**blueprint, "thumbnail_blueprint_rules": str(blueprint["content"])},
        language=str(task.get("language") or channel.get("language") or "Português"),
    )
    image_prompt = str(variant.get("image_prompt") or topic)
    headline = str(variant.get("overlay_text") or topic)
    # Fundo SEM texto: is_scene_image usa o prompt puro e NÃO leva lettering —
    # o texto nunca é gerado pela IA de imagem (regra dos blueprints).
    background = generate_image_from_pool(
        settings,
        image_prompt,
        topic=topic,
        variant_index=0,
        is_scene_image=True,
        aspect_ratio="16:9",
        thumbnail_blueprint=blueprint,
    )
    frame = apply_music_text_overlay(background, headline)
    return frame, variant


def run_music_clip_task(task: dict[str, Any], settings: dict[str, Any] | None = None, channel: dict[str, Any] | None = None) -> dict[str, Any]:
    """Devolve as actualizações do clip de música; quem chama persiste-as na tarefa."""
    settings = settings if isinstance(settings, dict) else {}
    channel = channel if isinstance(channel, dict) else {}
    music_path = resolve_music_source(task)
    if music_path is None:
        raise ValueError("Clipes de Música exige uma música existente na biblioteca ou um ficheiro carregado.")
    frame, variant = generate_music_clip_frame(task, settings, channel)

    from moviepy import AudioFileClip

    with AudioFileClip(str(music_path)) as audio:
        duration = max(2.0, float(getattr(audio, "duration", 0.0) or 30.0))
    video_path = Path(frame).parent / f"music-clip-{str(task.get('id') or 'clip')}.mp4"
    assemble_text_to_images_video(
        [{"image_path": str(frame), "duration": duration, "text": ""}],
        music_path,
        video_path,
        str(task.get("format") or "wide"),
        fps=30,
        ken_burns=True,
    )
    artifacts = dict(task.get("artifacts") or {})
    artifacts.update({"music": str(music_path), "video": str(video_path), "thumbnail": str(frame)})
    return {
        "stage": "video",
        "state": "done",
        "progress": 100,
        "artifacts": artifacts,
        "music_ready": True,
        "video_ready": True,
        "thumbnail_status": "generated",
        "thumbnail_prompt": str(variant.get("image_prompt") or ""),
        "error": None,
    }


__all__ = [
    "apply_music_text_overlay",
    "generate_music_clip_frame",
    "run_music_clip_task",
]