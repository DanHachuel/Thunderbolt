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


def assemble_text_to_images_video(
    scenes_with_images: list[dict],
    audio_path: Path,
    output_path: Path,
    format: str,
    fps: int = 30,
    ken_burns: bool = False,
) -> Path:
    """Assemble still images and audio using only project-provided MoviePy/FFmpeg.

    Ken Burns is accepted for API compatibility; the current dependency-safe
    implementation keeps still frames static when no compatible transform is available.
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
