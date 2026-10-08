from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from .provider_routing import ProviderRoutingError, route_llm_json
from .voice_preview import synthesize_preview


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


def generate_image_prompts_for_scenes(
    scenes: list[dict],
    style: str,
    settings: dict,
    channel: dict,
) -> list[dict]:
    """Generate one concise, text-free visual prompt per scene through the active LLM."""
    if not scenes:
        return []
    system = (
        "You are a cinematic storyboard artist. Return only valid JSON with a 'scenes' array. "
        "For every scene create an image prompt of no more than 240 characters. Never include words, letters, logos or watermarks. "
        "Prioritize dynamic composition, dramatic lighting, visual storytelling, palette and mood."
    )
    payload = {"style": style, "channel": channel, "scenes": [{"index": item.get("index"), "text": item.get("text", "")} for item in scenes]}
    try:
        response = route_llm_json(settings, system, json.dumps(payload, ensure_ascii=False))
        generated = response.payload.get("scenes") if isinstance(response.payload, dict) else None
    except (ProviderRoutingError, ValueError, TypeError):
        generated = None
    generated = generated if isinstance(generated, list) else []
    by_index = {int(item.get("index")): item for item in generated if isinstance(item, dict) and str(item.get("index", "")).isdigit()}
    output: list[dict[str, Any]] = []
    for scene in scenes:
        index = int(scene.get("index") or len(output) + 1)
        candidate = by_index.get(index, {})
        prompt = str(candidate.get("prompt") or candidate.get("Prompt") or "").strip()[:240]
        if not prompt:
            prompt = f"Cinematic scene, dramatic lighting, dynamic composition, visual storytelling about {str(scene.get('text') or '')[:160]}"
        output.append({**scene, "prompt": prompt})
    return output


def _subtitle_clips_for_scenes(scenes: list[dict], video_width: int, video_height: int, config: dict) -> list:
    """TextClips de legenda por cena, queimados na timeline da montagem.

    0.9.63: as Configurações de legendas existiam na UI e nos defaults por
    canal, mas a montagem por cenas nunca as aplicava — nenhum vídeo
    text_to_images/web_images saía com legendas.
    """
    from moviepy import TextClip

    font_path = str(config.get("font_path") or "")
    if not font_path:
        return []
    # O tamanho é definido para 1080p e escala com a altura real do vídeo.
    font_size = max(12, int(config.get("font_size") or 60) * max(1, int(video_height)) // 1080)
    position = str(config.get("position") or "bottom").strip().casefold()
    color = str(config.get("color") or "#FFFFFF")
    outline = str(config.get("outline") or "#000000")
    outline_width = int(round(float(config.get("outline_width") or 0)))
    background = bool(config.get("background"))
    background_color = str(config.get("background_color") or "#000000")
    wrap_width = max(120, int(video_width * 0.86))
    position_pair = {"top": ("center", "top"), "center": ("center", "center")}.get(position, ("center", "bottom"))
    offset = 0.0
    clips = []
    for scene in scenes:
        text = " ".join(str(scene.get("text") or "").split()).strip()
        duration = max(0.1, float(scene.get("duration") or 5.0))
        if text:
            kwargs: dict = {
                "text": text,
                "font": font_path,
                "font_size": font_size,
                "color": color,
                "method": "caption",
                "size": (wrap_width, None),
                "text_align": "center",
            }
            if outline_width > 0:
                kwargs["stroke_color"] = outline
                kwargs["stroke_width"] = outline_width
            if background:
                kwargs["bg_color"] = background_color
            clip = TextClip(**kwargs).with_duration(duration)
            clip = clip.with_start(offset).with_position(position_pair)
            clips.append(clip)
        offset += duration
    return clips


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


def synthesize_text_to_images_audio(text: str, settings: dict[str, Any], voice: str, output_path: Path) -> Path:
    """Synthesize narration in bounded chunks through the configured TTS provider."""
    service = str(settings.get("voiceover_service") or "Azure TTS V1")
    provider = {"Azure Speech SDK V2": "azure_speech", "Azure TTS V1": "azure_v1", "ElevenLabs": "elevenlabs"}.get(service, "azure_v1")
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
