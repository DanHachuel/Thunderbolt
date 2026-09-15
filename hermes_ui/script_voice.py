"""Convert persisted video-script Markdown into text suitable for narration."""

from __future__ import annotations

import re


_MARKER = re.compile(r"^\s*(?:\*\*)?\[\s*(VISUAL|NARRA(?:ÇÃO|CAO)|VOICEOVER|VOZ|ÁUDIO|AUDIO|SFX|SOM)\s*\](?:\*\*)?\s*:?[ \t]*$", re.IGNORECASE)
_TIME_HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?.*\(\s*\d{1,2}:\d{2}\s*[–—-]\s*\d{1,2}:\d{2}\s*\)\s*$", re.IGNORECASE)


def _strip_inline_markdown(line: str) -> str:
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"[`*_~]", "", line)
    return re.sub(r"\s+", " ", line).strip()


def narration_text_from_script(value: str) -> str:
    """Return only spoken prose from a Markdown video script.

    Titles, blockquote summaries, Markdown headings, timing labels, visual/audio
    directions and horizontal rules are editorial metadata and must not reach TTS.
    Explicit [NARRAÇÃO]/[VOICEOVER] blocks are supported and take precedence over
    unlabelled prose inside a visual block.
    """
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.splitlines()
    spoken: list[str] = []
    skip_visual = False
    explicit_voice = False
    voice_markers = {"narração", "narracao", "voiceover", "voz"}
    visual_markers = {"visual", "sfx", "som", "áudio", "audio"}
    marker_lines = [_MARKER.match(line) for line in lines]
    has_explicit_voice = any(match and match.group(1).casefold() in voice_markers for match in marker_lines)

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line == "---":
            continue
        marker_match = _MARKER.match(line)
        if marker_match:
            marker = marker_match.group(1).casefold()
            explicit_voice = marker in voice_markers
            skip_visual = marker in visual_markers
            continue
        if line.startswith(">") or re.match(r"^#{1,6}\s", line):
            continue
        if _TIME_HEADING.match(line) or line.casefold() in {"visual", *voice_markers, *visual_markers}:
            continue
        if line.startswith("#") or (line.startswith("[") and line.endswith("]")):
            continue
        if re.match(r"^\s*\*{0,2}(?:visual|narração|narracao|voiceover|voz|sfx|som|áudio|audio)\s*\*{0,2}\s*:", line, re.IGNORECASE):
            continue
        if skip_visual:
            continue
        if has_explicit_voice and not explicit_voice:
            continue
        clean = _strip_inline_markdown(line)
        if clean:
            spoken.append(clean)

    result = "\n\n".join(spoken).strip()
    if result:
        return result

    # Legacy scripts without section labels still receive a safe metadata-free fallback.
    fallback = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line == "---" or line.startswith(("#", ">")):
            continue
        if _TIME_HEADING.match(line) or _MARKER.match(line):
            continue
        clean = _strip_inline_markdown(line)
        if clean:
            fallback.append(clean)
    return "\n\n".join(fallback).strip()


__all__ = ["narration_text_from_script"]

