"""Convert persisted video-script Markdown into text suitable for narration."""

from __future__ import annotations

import re


_MARKER = re.compile(
    r"^\s*(?:\*\*)?\[\s*(VISUAL|NARRA(?:ÇÃO|CAO|TION)|VOICEOVER|VOICE\s*OVER|VOZ|ÁUDIO|AUDIO|SFX|SOM|ON[\s-]*SCREEN(?:\s*TEXT)?)\s*\](?:\*\*)?\s*:?[ \t]*$",
    re.IGNORECASE,
)
_TIME_HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?.*\(\s*\d{1,2}:\d{2}\s*[–—-]\s*\d{1,2}:\d{2}\s*\)\s*$", re.IGNORECASE)
_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)


def _strip_inline_markdown(line: str) -> str:
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"[`*_~]", "", line)
    return re.sub(r"\s+", " ", line).strip()


def narration_text_from_script(value: str) -> str:
    """Return only spoken prose from a Markdown video script.

    Titles, blockquote summaries, Markdown headings, timing labels, visual/audio
    directions and horizontal rules are editorial metadata and must not reach TTS.
    Explicit [NARRAÇÃO]/[NARRATION]/[VOICEOVER] blocks are supported and take
    precedence over unlabelled prose inside a visual block.

    1.0.03: os roteiros em inglês usam ``**[NARRATION]**`` (a regex só conhecia
    NARRAÇÃO/NARRACAO) e os corpos vêm em blockquotes ``>``, que eram sempre
    descartados — a narração extraída de um roteiro real reduzia-se a 28
    palavras do frontmatter do ficheiro (áudio de 16,85 s para um vídeo de
    10 minutos). Agora: o frontmatter YAML é removido, ``NARRATION`` e
    ``VOICE OVER`` são marcadores de voz, corpos em blockquote DENTRO de um
    bloco de narração são lidos (o prefixo ``>`` é retirado) e
    ``ON-SCREEN TEXT`` passa a família visual (texto de ecrã não se narra).
    """
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = _FRONTMATTER.sub("", raw, count=1)
    lines = raw.splitlines()
    spoken: list[str] = []
    skip_visual = False
    explicit_voice = False
    voice_markers = {"narração", "narracao", "narration", "voiceover", "voice over", "voz"}
    visual_markers = {"visual", "sfx", "som", "áudio", "audio", "on-screen text", "onscreen text", "on-screen", "onscreen"}
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
        if line.startswith(">"):
            # Blockquote: sumário editorial fora de bloco de narração; corpo
            # da narração DENTRO de um bloco **[NARRATION]** (o prefixo sai).
            if not explicit_voice:
                continue
            line = re.sub(r"^\s*>\s?", "", raw_line).strip()
            if not line:
                continue
        if line.startswith(">") or re.match(r"^#{1,6}\s", line):
            continue
        if _TIME_HEADING.match(line) or line.casefold() in {"visual", *voice_markers, *visual_markers}:
            continue
        if line.startswith("#") or (line.startswith("[") and line.endswith("]")):
            continue
        if re.match(r"^\s*\*{0,2}(?:visual|narração|narracao|narration|voiceover|voz|sfx|som|áudio|audio)\s*\*{0,2}\s*:", line, re.IGNORECASE):
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

