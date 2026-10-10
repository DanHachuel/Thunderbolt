"""Asset generation for Remotion format pipelines (0.9.76: format_id).

Extracts image prompts and TTS segments from the LLM-validated JSON, calls
the configured providers (reusing the existing pool/failover), and injects
the resulting local paths (imageUrl/audioUrl) back into the JSON as
inputProps for the Remotion render.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .storage import STORAGE

logger = logging.getLogger(__name__)


def _task_asset_dir(task_id: str, kind: str) -> Path:
    directory = STORAGE / "tasks" / task_id / kind
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# ---------------------------------------------------------------------------
# Extraction â€” one mapping per blueprint
# ---------------------------------------------------------------------------

def extract_image_prompts(llm_json: dict[str, Any], format_id: str) -> list[dict[str, str]]:
    """Return [{key, prompt}] with every image prompt in scene order."""
    prompts: list[dict[str, str]] = []
    if format_id == "inspirational":
        for scene in llm_json.get("scenes") or []:
            prompts.append({"key": scene.get("id", f"scene_{len(prompts)}"), "prompt": scene.get("image_prompt", "")})
    elif format_id == "social_reel":
        for scene in llm_json.get("scenes") or []:
            prompts.append({"key": scene.get("id", f"scene_{len(prompts)}"), "prompt": scene.get("imagePrompt", "")})
    elif format_id == "top_10":
        intro = llm_json.get("intro") or {}
        if intro.get("imagePrompt"):
            prompts.append({"key": "intro", "prompt": intro["imagePrompt"]})
        for item in llm_json.get("ranking") or []:
            prompts.append({"key": f"rank_{item.get('rank', len(prompts))}", "prompt": item.get("imagePrompt", "")})
        outro = llm_json.get("outro") or {}
        if outro.get("imagePrompt"):
            prompts.append({"key": "outro", "prompt": outro["imagePrompt"]})
    elif format_id == "would_you_rather":
        for question in llm_json.get("questions") or []:
            qid = question.get("id", f"q{len(prompts) // 2 + 1}")
            prompts.append({"key": f"{qid}_option1", "prompt": question.get("option1_image_prompt", "")})
            prompts.append({"key": f"{qid}_option2", "prompt": question.get("option2_image_prompt", "")})
    # quiz_videos: no image prompts (background-only); skip.
    return [p for p in prompts if p["prompt"]]


def extract_tts_segments(llm_json: dict[str, Any], format_id: str) -> list[dict[str, str]]:
    """Return [{key, text}] with every TTS segment in playback order."""
    segments: list[dict[str, str]] = []
    if format_id == "inspirational":
        for scene in llm_json.get("scenes") or []:
            segments.append({"key": scene.get("id", f"scene_{len(segments)}"), "text": scene.get("voiceover_text", "")})
    elif format_id == "social_reel":
        for scene in llm_json.get("scenes") or []:
            segments.append({"key": scene.get("id", f"scene_{len(segments)}"), "text": scene.get("voiceOverText", "")})
    elif format_id == "quiz":
        if llm_json.get("intro_voiceover"):
            segments.append({"key": "intro", "text": llm_json["intro_voiceover"]})
        for q in llm_json.get("questions") or []:
            segments.append({"key": f"q{len(segments)}", "text": q.get("question", "")})
        if llm_json.get("like_and_subscribe_voiceover"):
            segments.append({"key": "outro", "text": llm_json["like_and_subscribe_voiceover"]})
    elif format_id == "top_10":
        intro = llm_json.get("intro") or {}
        if intro.get("voiceoverText"):
            segments.append({"key": "intro", "text": intro["voiceoverText"]})
        for item in llm_json.get("ranking") or []:
            segments.append({"key": f"rank_{item.get('rank', len(segments))}", "text": item.get("voiceoverText", "")})
        outro = llm_json.get("outro") or {}
        if outro.get("voiceoverText"):
            segments.append({"key": "outro", "text": outro["voiceoverText"]})
    elif format_id == "would_you_rather":
        if llm_json.get("like_and_subscribe_voiceover_text"):
            segments.append({"key": "outro", "text": llm_json["like_and_subscribe_voiceover_text"]})
        for question in llm_json.get("questions") or []:
            segments.append({"key": question.get("id", f"q{len(segments)}"), "text": question.get("voiceover_text", "")})
    return [s for s in segments if s["text"]]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _generate_image(provider: Callable, prompt: str, output: Path, task_id: str) -> Path | None:
    """Call the image provider and save to output path. Returns the path or None."""
    try:
        result = provider(prompt)
        if result is None:
            return None
        if isinstance(result, Path):
            if result != output:
                output.write_bytes(result.read_bytes())
            return output
        if isinstance(result, bytes):
            output.write_bytes(result)
            return output
        if isinstance(result, str):
            source = Path(result)
            if source.is_file():
                output.write_bytes(source.read_bytes())
                return output
        return None
    except Exception as exc:
        logger.warning("Image provider falhou para %s (%s): %s", output.name, task_id, exc)
        return None


def _generate_tts(provider: Callable, text: str, output: Path, task_id: str) -> Path | None:
    """Call the TTS provider and save to output path. Returns the path or None."""
    try:
        result = provider(text)
        if result is None:
            return None
        if isinstance(result, Path):
            if result != output:
                output.write_bytes(result.read_bytes())
            return output
        if isinstance(result, bytes):
            output.write_bytes(result)
            return output
        if isinstance(result, str):
            source = Path(result)
            if source.is_file():
                output.write_bytes(source.read_bytes())
                return output
        return None
    except Exception as exc:
        logger.warning("TTS provider falhou para %s (%s): %s", output.name, task_id, exc)
        return None


def generate_assets(
    task: dict[str, Any],
    llm_json: dict[str, Any],
    format_id: str,
    image_provider: Callable,
    tts_provider: Callable,
    max_workers: int = 4,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Generate all images and TTS audio, return the JSON with assets injected.

    The cancel_check is called between batches; if it returns True, stop
    immediately and raise a PipelineStopped-like exception.
    """
    import copy

    task_id = str(task.get("id") or "blueprint")
    image_dir = _task_asset_dir(task_id, "images")
    audio_dir = _task_asset_dir(task_id, "audio")

    # --- images (parallel) ---
    image_prompts = extract_image_prompts(llm_json, format_id)
    image_paths: dict[str, Path] = {}

    def render_image(item: dict[str, str]) -> tuple[str, Path | None]:
        key = item["key"]
        output = image_dir / f"{key}.png"
        return key, _generate_image(image_provider, item["prompt"], output, task_id)

    if image_prompts:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(render_image, item): item for item in image_prompts}
            for future in futures:
                if cancel_check and cancel_check():
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise RuntimeError("Tarefa cancelada durante a geraÃ§Ã£o de assets.")
                key, path = future.result()
                if path:
                    image_paths[key] = path

    # --- TTS (serial to preserve order and avoid rate limits) ---
    tts_segments = extract_tts_segments(llm_json, format_id)
    audio_paths: dict[str, Path] = {}
    for segment in tts_segments:
        if cancel_check and cancel_check():
            raise RuntimeError("Tarefa cancelada durante a geraÃ§Ã£o de assets.")
        key = segment["key"]
        output = audio_dir / f"{key}.mp3"
        path = _generate_tts(tts_provider, segment["text"], output, task_id)
        if path:
            audio_paths[key] = path

    # --- inject into JSON ---
    assets_map = {
        "images": {key: str(path) for key, path in image_paths.items()},
        "audio": {key: str(path) for key, path in audio_paths.items()},
    }
    enriched = inject_assets(llm_json, assets_map, format_id)
    return enriched


# ---------------------------------------------------------------------------
# Injection â€” add imageUrl/audioUrl at the correct locations per blueprint
# ---------------------------------------------------------------------------

def inject_assets(llm_json: dict[str, Any], assets_map: dict[str, Any], format_id: str) -> dict[str, Any]:
    """Return a deep copy of the JSON with imageUrl/audioUrl added. Never removes keys."""
    import copy

    enriched = copy.deepcopy(llm_json)
    images = assets_map.get("images") or {}
    audio = assets_map.get("audio") or {}

    if format_id in ("inspirational", "social_reel"):
        for scene in enriched.get("scenes") or []:
            key = scene.get("id", "")
            if key in images:
                scene["imageUrl"] = images[key]
            if key in audio:
                scene["audioUrl"] = audio[key]

    elif format_id == "quiz":
        if "intro" in audio:
            enriched["introAudioUrl"] = audio["intro"]
        for index, question in enumerate(enriched.get("questions") or []):
            qkey = f"q{index + 1}"
            if qkey in audio:
                question["audioUrl"] = audio[qkey]
        if "outro" in audio:
            enriched["outroAudioUrl"] = audio["outro"]

    elif format_id == "top_10":
        intro = enriched.get("intro") or {}
        if "intro" in images:
            intro["imageUrl"] = images["intro"]
        if "intro" in audio:
            intro["audioUrl"] = audio["intro"]
        for item in enriched.get("ranking") or []:
            rank_key = f"rank_{item.get('rank', '')}"
            if rank_key in images:
                item["imageUrl"] = images[rank_key]
            if rank_key in audio:
                item["audioUrl"] = audio[rank_key]
        outro = enriched.get("outro") or {}
        if "outro" in images:
            outro["imageUrl"] = images["outro"]
        if "outro" in audio:
            outro["audioUrl"] = audio["outro"]

    elif format_id == "would_you_rather":
        for question in enriched.get("questions") or []:
            qid = question.get("id", "")
            if f"{qid}_option1" in images:
                question["option1_imageUrl"] = images[f"{qid}_option1"]
            if f"{qid}_option2" in images:
                question["option2_imageUrl"] = images[f"{qid}_option2"]
            if qid in audio:
                question["audioUrl"] = audio[qid]
        if "outro" in audio:
            enriched["outroAudioUrl"] = audio["outro"]

    return enriched
