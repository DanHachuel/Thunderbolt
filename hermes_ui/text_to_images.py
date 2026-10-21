from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from .blueprint_governance import visual_requirements_prompt_section
from .provider_routing import ProviderRoutingError, route_llm_json
from .voice_preview import resolve_narration_provider, synthesize_preview


def _duration_from_words(words: list[dict[str, Any]], fallback_wpm: int) -> float:
    timestamps = []
    for word in words:
        if not isinstance(word, dict):
            continue
        start = word.get("start", word.get("start_time"))
        end = word.get("end", word.get("end_time"))
        try:
            if start is not None and end is not None:
                timestamps.append((float(start), float(end)))
        except (TypeError, ValueError):
            continue
    if timestamps:
        return max(0.1, max(end for _, end in timestamps))
    return max(0.1, len(words) / max(1, fallback_wpm) * 60.0)


def split_script_into_scenes(
    script_text: str,
    words_data: list[dict] | None = None,
    target_seconds: float = 5.0,
    wpm: int = 150,
) -> list[dict]:
    """Split narration into scenes near target_seconds.

    Word timestamps are used when available. Without timestamps, duration is
    estimated from word count and ``wpm``; this fallback cannot reflect pauses
    or pronunciation speed and is therefore only an approximation.
    """
    words = re.findall(r"\S+", str(script_text or "").strip())
    if not words:
        return []
    target = max(0.5, float(target_seconds or 5.0))
    timed = [item for item in (words_data or []) if isinstance(item, dict)]
    result: list[dict[str, Any]] = []
    if timed and len(timed) >= len(words):
        start_index = 0
        scene_start = 0.0
        for index, word in enumerate(words):
            item = timed[index]
            try:
                end = float(item.get("end", item.get("end_time")))
            except (TypeError, ValueError):
                end = scene_start + target
            if end - scene_start >= target and index >= start_index:
                result.append({"text": " ".join(words[start_index:index + 1]), "start": scene_start, "end": end, "duration": max(0.1, end - scene_start)})
                start_index = index + 1
                scene_start = end + 0.1
        if start_index < len(words):
            end = max(scene_start + 0.1, _duration_from_words(timed[start_index:], wpm))
            result.append({"text": " ".join(words[start_index:]), "start": scene_start, "end": end, "duration": max(0.1, end - scene_start)})
    else:
        words_per_scene = max(1, round(max(1, wpm) * target / 60.0))
        for start in range(0, len(words), words_per_scene):
            chunk = words[start:start + words_per_scene]
            duration = max(0.1, len(chunk) / max(1, wpm) * 60.0 + 0.1)
            scene_start = result[-1]["end"] + 0.1 if result else 0.0
            result.append({"text": " ".join(chunk), "start": scene_start, "end": scene_start + duration, "duration": duration})
    if len(result) > 1 and result[-1]["duration"] < 2.0:
        previous = result[-2]
        previous["text"] = f"{previous['text']} {result[-1]['text']}".strip()
        previous["end"] = result[-1]["end"]
        previous["duration"] = previous["end"] - previous["start"]
        result.pop()
    for index, scene in enumerate(result, start=1):
        scene["index"] = index
    return result


def _scene_text_overlay_positions(scene_count: int) -> set[int]:
    """Índices (0-based) das cenas que podem receber texto — máx. 5%, distribuição uniforme.

    1.0.04: no máximo 5% das cenas (`max(1, int(count * 0.05))`) recebem um
    texto curto queimado na imagem; as restantes saem estritamente sem texto.
    Com uma única cena marcada fica no meio; com várias, distribui-se do
    início ao fim em passos uniformes (início/meio/fim).
    """
    if scene_count <= 0:
        return set()
    limit = max(1, int(scene_count * 0.05))
    if limit >= scene_count:
        return set(range(scene_count))
    if limit == 1:
        return {scene_count // 2}
    return {round(index * (scene_count - 1) / (limit - 1)) for index in range(limit)}


def _sanitise_text_overlay(value: Any) -> str:
    """Mantém o overlay curto e legível: máximo 3 palavras e 32 caracteres."""
    words = re.findall(r"[\wÀ-ÿ'’!?$%+-]+", str(value or ""), flags=re.UNICODE)
    return " ".join(words[:3])[:32].strip()


def generate_image_prompts_for_scenes(
    scenes: list[dict],
    style: str,
    settings: dict,
    channel: dict,
    blueprint: dict | None = None,
) -> list[dict]:
    """Generate one concise, text-free visual prompt per scene through the active LLM.

    1.0.04: até 5% das cenas (distribuição uniforme) podem receber um texto
    curto (máx. 3 palavras) queimado na imagem — devolvido pela LLM no campo
    `text_overlay` e injectado no prompt como "with the text 'X' written on
    it.". Todas as restantes saem estritamente sem texto. Se a LLM falhar, o
    fallback não injecta texto nenhum (0% é sempre seguro).

    1.0.17: os requisitos visuais do canal vêm do Blueprint
    (``metadata.visual_requirements`` — instrução + keywords a favorecer +
    keywords proibidas) e são injectados no system prompt: o motor não faz
    hardcoding; cada nicho dita as suas regras de imagem pelo seu JSON.
    """
    if not scenes:
        return []
    text_positions = _scene_text_overlay_positions(len(scenes))
    system = (
        "You are a cinematic storyboard artist. Return only valid JSON with a 'scenes' array. "
        "For every scene create an image prompt of no more than 240 characters. Never include words, letters, logos or watermarks. "
        "Prioritize dynamic composition, dramatic lighting, visual storytelling, palette and mood. "
        "For scenes marked with \"allow_text\": true, also generate a short, punchy text overlay "
        "(maximum 3 words) in the field 'text_overlay'. For all other scenes, strictly NO text "
        "and 'text_overlay' must be empty."
    )
    # 1.0.17: a lei visual do canal (ex.: «majestic nature, ABSOLUTELY NO
    # HUMANS») entra no system prompt quando o blueprint a define.
    visual_section = visual_requirements_prompt_section(blueprint)
    if visual_section:
        system += "\n\n" + visual_section
    payload = {
        "style": style,
        "channel": channel,
        "scenes": [
            {
                "index": item.get("index"),
                "text": item.get("text", ""),
                "allow_text": position in text_positions,
            }
            for position, item in enumerate(scenes)
        ],
    }
    try:
        response = route_llm_json(settings, system, json.dumps(payload, ensure_ascii=False))
        generated = response.payload.get("scenes") if isinstance(response.payload, dict) else None
    except (ProviderRoutingError, ValueError, TypeError):
        generated = None
    generated = generated if isinstance(generated, list) else []
    by_index = {int(item.get("index")): item for item in generated if isinstance(item, dict) and str(item.get("index", "")).isdigit()}
    output: list[dict[str, Any]] = []
    for position, scene in enumerate(scenes):
        index = int(scene.get("index") or len(output) + 1)
        candidate = by_index.get(index, {})
        prompt = str(candidate.get("prompt") or candidate.get("Prompt") or "").strip()[:240]
        overlay = _sanitise_text_overlay(candidate.get("text_overlay")) if position in text_positions else ""
        if not prompt:
            prompt = f"Cinematic scene, dramatic lighting, dynamic composition, visual storytelling about {str(scene.get('text') or '')[:160]}"
        if overlay:
            prompt = f"{prompt} with the text '{overlay}' written on it."
        output.append({**scene, "prompt": prompt})
    return output


def _subtitle_rgba(value: Any, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Converte '#RGB'/'#RRGGBB'/'#RRGGBBAA' numa tupla RGBA; inválido devolve o fallback."""
    raw = str(value or "").strip()
    hex_part = raw[1:] if raw.startswith("#") else ""
    if len(hex_part) == 3:
        hex_part = "".join(ch * 2 for ch in hex_part)
    if len(hex_part) in (6, 8):
        try:
            channels = [int(hex_part[i : i + 2], 16) for i in range(0, len(hex_part), 2)]
        except ValueError:
            channels = []
        # 1.0.09: '#RRGGBB' produz 3 canais (RGB) e '#RRGGBBAA' produz 4
        # (RGBA). A validação antiga `len(channels) in (6, 8)` rejeitava
        # SEMPRE os canais e o padding `8 - len(channels)` devolvia uma
        # tupla de 8 elementos — qualquer cor válida caía no fallback: as
        # cores escolhidas nas Configurações de legendas eram silenciosamente
        # ignoradas na queima real (texto branco, contorno e fundo pretos).
        if len(channels) in (3, 4):
            return tuple(channels + [255] * (4 - len(channels)))
    return fallback


def _wrap_text_pixels(text: str, font: Any, max_width: int) -> list[str]:
    """Quebra o texto em linhas que cabem em max_width, medidas em pixels com a própria fonte.

    O wrap não pode ficar a cargo do TextClip: além de a caixa final passar a
    ser hug-text (largura da maior linha + padding), palavras isoladas maiores
    que a largura (URLs, palavras longas) são divididas por caracteres em vez
    de transbordarem a caixa.
    """
    words = str(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if not current or font.getlength(candidate) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
    if current:
        lines.append(current)
    fitted: list[str] = []
    for line in lines:
        if len(line) <= 1 or font.getlength(line) <= max_width:
            fitted.append(line)
            continue
        chunk = ""
        for char in line:
            if chunk and font.getlength(chunk + char) > max_width:
                fitted.append(chunk)
                chunk = char
            else:
                chunk += char
        if chunk:
            fitted.append(chunk)
    return fitted


def _subtitle_clips_for_scenes(scenes: list[dict], video_width: int, video_height: int, config: dict) -> list:
    """Clips de legenda por cena, queimados na timeline da montagem.

    0.9.63: as Configurações de legendas existiam na UI e nos defaults por
    canal, mas a montagem por cenas nunca as aplicava — nenhum vídeo
    text_to_images/web_images saía com legendas.

    1.0.00: o TextClip em modo caption com cor de fundo desenhava uma barra
    preta full-width (o fundo pinta a canvas inteira, cuja largura é forçada
    por size[0]) e cortava a base das letras: a Pillow 11 removeu
    draw._multiline_spacing e o MoviePy passou a calcular a altura pelo bbox
    de tinta do texto enquanto desenhava a baseline pela métrica da fonte —
    a MicrosoftYaHeiBold.ttc tem ascent interno ~1.4x a altura visível das
    maiúsculas, e a tinta descia abaixo da canvas. Cada cena passa a ser
    desenhada com PIL: wrap medido em pixels, layout de baseline pelas
    métricas reais da fonte (ascendentes/descendentes nunca cortados) e caixa
    hug-text recortada sobre a tinta real com padding uniforme.
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from moviepy import ImageClip

    font_path = str(config.get("font_path") or "")
    if not font_path:
        return []
    # O tamanho é definido para 1080p e escala com a altura real do vídeo.
    font_size = max(12, int(config.get("font_size") or 40) * max(1, int(video_height)) // 1080)
    font = ImageFont.truetype(font_path, font_size)
    ascent, descent = font.getmetrics()

    position = str(config.get("position") or "bottom").strip().casefold()
    color = _subtitle_rgba(config.get("color"), (255, 255, 255, 255))
    stroke_color = _subtitle_rgba(config.get("outline"), (0, 0, 0, 255))
    stroke_width = max(0, int(round(float(config.get("outline_width") or 0))))
    background = bool(config.get("background"))
    background_color = _subtitle_rgba(config.get("background_color"), (0, 0, 0, 255))
    # Padding uniforme entre a tinta do texto e a borda do fundo (10-15 px em 1080p).
    padding = max(10, min(15, round(font_size * 0.25)))
    interline = max(4, round(font_size * 0.25))
    wrap_width = max(120, int(video_width * 0.86))
    max_text_width = max(40, wrap_width - 2 * padding)
    offset = 0.0
    clips = []
    for scene in scenes:
        text = " ".join(str(scene.get("text") or "").split()).strip()
        duration = max(0.1, float(scene.get("duration") or 5.0))
        if text:
            lines = _wrap_text_pixels(text, font, max_text_width)
            text_width = max(math.ceil(font.getlength(line)) for line in lines)
            # Canvas generoso com layout métrico: a baseline de cada linha fica
            # a padding+stroke da borda e o avanço de linha usa ascent+descent
            # reais da fonte — nenhum glifo (Q, g, p, y, ç, ã) sai da canvas.
            margin = padding + stroke_width
            line_advance = ascent + descent + interline
            canvas_w = text_width + 2 * margin
            canvas_h = len(lines) * (ascent + descent) + (len(lines) - 1) * interline + 2 * margin
            img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            for index, line in enumerate(lines):
                baseline = margin + ascent + index * line_advance
                x = margin + (text_width - font.getlength(line)) / 2
                draw.text(
                    (x, baseline),
                    line,
                    font=font,
                    fill=color,
                    anchor="ls",
                    stroke_width=stroke_width,
                    stroke_fill=stroke_color if stroke_width else None,
                )
            # Caixa hug-text: mede a tinta real desenhada (inclui o contorno)
            # e recorta o ImageClip à caixa expandida com o padding uniforme
            # nas quatro direções. O fundo é composto numa camada própria
            # ATRÁS da tinta — pintá-lo sobre a canvas apagava o texto.
            alpha = np.array(img)[:, :, 3]
            ink_rows, ink_cols = np.where(alpha > 0)
            if ink_rows.size:
                left = max(0, int(ink_cols.min()) - padding)
                top = max(0, int(ink_rows.min()) - padding)
                right = min(canvas_w, int(ink_cols.max()) + 1 + padding)
                bottom = min(canvas_h, int(ink_rows.max()) + 1 + padding)
                box = Image.new("RGBA", (right - left, bottom - top), background_color if background else (0, 0, 0, 0))
                box.alpha_composite(img.crop((left, top, right, bottom)))
                img = box
            # 1.0.10: margem vertical dinâmica em "top"/"bottom" — a legenda
            # afasta-se da borda exactamente a altura do próprio bloco
            # (caixa de fundo quando activa; tinta+contorno+padding sem fundo),
            # a mesma matemática do Preview (WYSIWYG). "center" fica centrado.
            block_height = int(img.size[1])
            if position == "top":
                clip_position: tuple[Any, Any] = ("center", block_height)
            elif position == "center":
                clip_position = ("center", "center")
            else:
                clip_position = ("center", max(0, int(video_height) - 2 * block_height))
            clip = ImageClip(np.array(img), transparent=True).with_duration(duration)
            clip = clip.with_start(offset).with_position(clip_position)
            clips.append(clip)
        offset += duration
    return clips


SUBTITLE_PREVIEW_PHRASE = "Lorem ipsum dolor sit amet consectetur adipiscing elit"


def render_subtitle_preview_frame(config: Mapping[str, Any], canvas_color: str = "#d3c4e3") -> "Image.Image":
    """Frame 1920x1080 com a legenda de teste queimada sobre um fundo de teste.

    1.0.09: preview das "Configurações de legendas" do card do canal. Replica a
    matemática de `_subtitle_clips_for_scenes` (tamanho da fonte escalado pela
    altura do vídeo, wrap medido em pixels, baseline pelas métricas reais da
    fonte, caixa hug-text com padding uniforme e fundo composto ATRÁS da
    tinta) num único frame, para a frase fixa `SUBTITLE_PREVIEW_PHRASE`.

    `canvas_color` pinta apenas o fundo do bloco de visualização — simula o
    fundo do vídeo e nunca afecta a legenda real. `rounded` espelha a rota
    MPT (`--rounded-subtitle-background`): cantos arredondados só com o fundo
    activo, como o pipeline envia ao motor.

    config: font_path, font_size, position ("top"/"center"/"bottom"), color,
    background, background_color, rounded, outline, outline_width.
    """
    from PIL import Image, ImageDraw, ImageFont

    font_path = str(config.get("font_path") or "")
    if not font_path:
        raise ValueError("Não foi possível encontrar a fonte das legendas para o preview.")
    # As métricas da montagem real: o tamanho é definido para 1080p e escala
    # com a altura real do vídeo — no preview o frame é 1080p, logo o slider
    # é aplicado tal qual.
    video_width, video_height = 1920, 1080
    font_size = max(12, int(config.get("font_size") or 40) * max(1, int(video_height)) // 1080)
    font = ImageFont.truetype(font_path, font_size)
    ascent, descent = font.getmetrics()

    position = str(config.get("position") or "bottom").strip().casefold()
    color = _subtitle_rgba(config.get("color"), (255, 255, 255, 255))
    stroke_color = _subtitle_rgba(config.get("outline"), (0, 0, 0, 255))
    stroke_width = max(0, int(round(float(config.get("outline_width") or 0))))
    background = bool(config.get("background"))
    background_color = _subtitle_rgba(config.get("background_color"), (0, 0, 0, 255))
    rounded = bool(config.get("rounded"))
    padding = max(10, min(15, round(font_size * 0.25)))
    interline = max(4, round(font_size * 0.25))
    wrap_width = max(120, int(video_width * 0.86))
    max_text_width = max(40, wrap_width - 2 * padding)

    lines = _wrap_text_pixels(SUBTITLE_PREVIEW_PHRASE, font, max_text_width) or [SUBTITLE_PREVIEW_PHRASE]
    text_width = max(math.ceil(font.getlength(line)) for line in lines)
    margin = padding + stroke_width
    line_advance = ascent + descent + interline
    canvas_w = text_width + 2 * margin
    canvas_h = len(lines) * (ascent + descent) + (len(lines) - 1) * interline + 2 * margin
    caption = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(caption)
    for index, line in enumerate(lines):
        baseline = margin + ascent + index * line_advance
        x = margin + (text_width - font.getlength(line)) / 2
        draw.text(
            (x, baseline),
            line,
            font=font,
            fill=color,
            anchor="ls",
            stroke_width=stroke_width,
            stroke_fill=stroke_color if stroke_width else None,
        )
    # Caixa hug-text idêntica à montagem: bbox da tinta real desenhada
    # (inclui o contorno) expandida com o padding uniforme nas quatro pontas.
    ink = caption.getchannel("A").getbbox()
    if ink:
        left = max(0, ink[0] - padding)
        top = max(0, ink[1] - padding)
        right = min(canvas_w, ink[2] + padding)
        bottom = min(canvas_h, ink[3] + padding)
        box = Image.new("RGBA", (right - left, bottom - top), background_color if background else (0, 0, 0, 0))
        if background and rounded:
            mask = Image.new("L", box.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, box.width - 1, box.height - 1], radius=max(4, padding), fill=255)
            box.putalpha(mask)
        box.alpha_composite(caption.crop((left, top, right, bottom)))
        caption = box
    frame = Image.new("RGB", (video_width, video_height), _subtitle_rgba(canvas_color, (211, 196, 227, 255))[:3])
    frame = frame.convert("RGBA")
    # 1.0.10: margem vertical dinâmica idêntica à montagem real (WYSIWYG) —
    # "top" desce e "bottom" sobe exactamente a altura do próprio bloco;
    # "center" mantém-se centrado.
    block_height = int(caption.height)
    if "top" in position:
        paste_y = block_height
    elif "center" in position or "middle" in position:
        paste_y = (video_height - block_height) // 2
    else:
        paste_y = max(0, video_height - 2 * block_height)
    paste_x = max(0, (video_width - caption.width) // 2)
    frame.alpha_composite(caption, (paste_x, paste_y))
    return frame.convert("RGB")


def assemble_text_to_images_video(
    scenes_with_images: list[dict],
    audio_path: Path,
    output_path: Path,
    format: str,
    fps: int = 30,
    ken_burns: bool = False,
    subtitle_config: dict | None = None,
) -> Path:
    """Assemble still images and audio using only project-provided MoviePy/FFmpeg.

    Ken Burns is accepted for API compatibility; the current dependency-safe
    implementation keeps still frames static when no compatible transform is available.

    Com `subtitle_config` (Configurações de legendas), cada cena queima o seu
    texto como legenda — fonte, tamanho, cor, contorno, fundo e posição —
    sincronizado com a duração da cena.
    """
    del format, ken_burns
    if not scenes_with_images:
        raise ValueError("Não existem cenas com imagens para montar o vídeo.")
    from moviepy import AudioFileClip, ImageClip, concatenate_videoclips

    clips = []
    audio = None
    try:
        for scene in scenes_with_images:
            image = Path(str(scene.get("image_path") or ""))
            if not image.is_file():
                raise FileNotFoundError(f"Imagem da cena não encontrada: {image}")
            duration = max(0.1, float(scene.get("duration") or 5.0))
            clips.append(ImageClip(str(image)).with_duration(duration))
        video = concatenate_videoclips(clips, method="compose")
        if subtitle_config:
            try:
                subtitle_clips = _subtitle_clips_for_scenes(
                    scenes_with_images,
                    int(video.size[0]),
                    int(video.size[1]),
                    subtitle_config,
                )
                if subtitle_clips:
                    from moviepy import CompositeVideoClip

                    video = CompositeVideoClip([video, *subtitle_clips]).with_duration(video.duration)
            except Exception as exc:
                # A legenda nunca pode destruir o vídeo: falha de fonte/PIL cai
                # para a montagem simples e o motivo fica no stderr do worker.
                import sys as _sys

                print(f"[text_to_images] legendas ignoradas por falha: {exc}", file=_sys.stderr)
        audio = AudioFileClip(str(audio_path))
        video = video.with_audio(audio)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        video.write_videofile(str(output_path), fps=max(1, int(fps or 30)), codec="libx264", audio_codec="aac", logger=None)
    finally:
        for clip in clips:
            close = getattr(clip, "close", None)
            if close:
                close()
        if audio is not None:
            close = getattr(audio, "close", None)
            if close:
                close()
    return output_path


def burn_captions_on_video(
    video_path: Path | str,
    text: str,
    subtitle_config: dict,
    *,
    target_seconds: float = 5.0,
    wpm: int = 150,
) -> Path:
    """Queima legendas aproximadas num vídeo final (rota Pexels/Pixabay do MPT).

    0.9.64: o MPT salta as legendas quando o áudio chega como ficheiro
    customizado ("subtitle maker is missing") — o Thunderbolt divide o texto
    em segmentos com duração estimada, reescala para a duração real do vídeo
    e queima as legendas com o mesmo motor/estilo das outras fontes. O
    ficheiro original é substituído in-place (o artefacto da tarefa mantém-se
    válido). Qualquer falha deixa o vídeo original intacto.
    """
    import os

    from moviepy import CompositeVideoClip, VideoFileClip

    output = Path(video_path)
    segments = split_script_into_scenes(str(text or ""), target_seconds=target_seconds, wpm=wpm)
    if not segments:
        segments = [{"index": 1, "text": str(text or "").strip()[:200], "duration": target_seconds}]
    video = None
    burned = None
    try:
        video = VideoFileClip(str(output))
        total = max(1.0, float(video.duration or 0))
        estimated = sum(max(0.4, float(item.get("duration") or target_seconds)) for item in segments) or target_seconds
        for item in segments:
            item["duration"] = max(0.4, float(item.get("duration") or target_seconds) * total / estimated)
        subtitle_clips = _subtitle_clips_for_scenes(
            segments,
            int(video.size[0]),
            int(video.size[1]),
            subtitle_config,
        )
        if not subtitle_clips:
            return output
        burned = CompositeVideoClip([video, *subtitle_clips]).with_duration(total)
        temporary = output.with_name(f"{output.stem}.legendas-tmp.mp4")
        burned.write_videofile(str(temporary), fps=max(1, int(video.fps or 30)), codec="libx264", audio_codec="aac", logger=None)
        burned.close()
        burned = None
        # 1.0.00: o CompositeVideoClip.close() não fecha os clips membros — o
        # leitor do vídeo original mantinha o ficheiro aberto e o os.replace
        # falhava no Windows (WinError 5) depois de a queima já estar feita.
        # Fechar o leitor antes do replace garante a substituição in-place.
        video.close()
        video = None
        os.replace(temporary, output)
        return output
    finally:
        for clip in (burned, video):
            if clip is not None:
                close = getattr(clip, "close", None)
                if close:
                    try:
                        close()
                    except Exception:
                        pass


def synthesize_text_to_images_audio(text: str, settings: dict[str, Any], voice: str, output_path: Path) -> Path:
    """Synthesize narration in bounded chunks through the configured TTS provider."""
    # 1.0.02: "Azure TTS V1" era mapeado cegamente para o edge (provider morto
    # desde Out/2026 — 403 em speech.platform.bing.com). O provider real passa
    # a ser resolvido por credenciais: com Azure Speech configurada usa-se o
    # endpoint oficial; sem credenciais o edge é bloqueado com mensagem clara.
    provider = resolve_narration_provider(settings.get("voiceover_service"), settings)
    import sys as _sys

    print(
        f"[tts] provider={provider} service={str(settings.get('voiceover_service') or 'Azure TTS V1').strip() or 'Azure TTS V1'} voice={str(voice).strip()}",
        file=_sys.stderr,
    )
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("O roteiro está vazio; não é possível gerar narração.")
    words = clean.split()
    chunks: list[str] = []
    current: list[str] = []
    for word in words:
        if current and len(" ".join(current + [word])) > 900:
            chunks.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        chunks.append(" ".join(current))
    files = [synthesize_preview(chunk, provider, voice, settings) for chunk in chunks]
    if len(files) == 1:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(files[0].read_bytes())
        return output_path
    from moviepy import AudioFileClip, concatenate_audioclips
    clips = [AudioFileClip(str(path)) for path in files]
    try:
        combined = concatenate_audioclips(clips)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.write_audiofile(str(output_path), codec="libmp3lame", logger=None)
    finally:
        for clip in clips:
            close = getattr(clip, "close", None)
            if close:
                close()
    return output_path


__all__ = ["split_script_into_scenes", "generate_image_prompts_for_scenes", "assemble_text_to_images_video", "synthesize_text_to_images_audio"]
