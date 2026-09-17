#!/usr/bin/env python3
"""Validate YouTube-friendly MP4 video encoding with ffprobe."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _probe(path: Path) -> dict:
    command = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


def _top_level_atoms(path: Path) -> list[str]:
    atoms: list[str] = []
    with path.open("rb") as handle:
        while True:
            header = handle.read(8)
            if len(header) < 8:
                break
            size = int.from_bytes(header[:4], "big")
            atom = header[4:8].decode("ascii", errors="replace")
            atoms.append(atom)
            if size == 1:
                extended = handle.read(8)
                if len(extended) < 8:
                    break
                size = int.from_bytes(extended, "big")
            if size < 8:
                break
            handle.seek(size - 8, 1)
    return atoms


def validate(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"Ficheiro inexistente: {path}")
    payload = _probe(path)
    format_name = str(payload.get("format", {}).get("format_name", ""))
    if "mp4" not in format_name.split(","):
        raise ValueError(f"Container incompatível: {format_name or 'desconhecido'}")
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video or video.get("codec_name") != "h264":
        raise ValueError(f"Codec de vídeo incompatível: {video or 'ausente'}")
    if not audio or audio.get("codec_name") != "aac":
        raise ValueError(f"Codec de áudio incompatível: {audio or 'ausente'}")
    if int(audio.get("channels") or 0) != 2:
        raise ValueError(f"Áudio não estéreo: {audio.get('channels') if audio else 'ausente'} canais")
    sample_rate = int(audio.get("sample_rate") or 0)
    if sample_rate not in {44100, 48000}:
        raise ValueError(f"Frequência de áudio incompatível: {sample_rate} Hz")
    atoms = _top_level_atoms(path)
    if "moov" not in atoms or "mdat" not in atoms or atoms.index("moov") > atoms.index("mdat"):
        raise ValueError(f"MP4 sem faststart: átomos de topo {atoms}")
    print(json.dumps({
        "path": str(path.resolve()),
        "size": path.stat().st_size,
        "format": format_name,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "channels": audio.get("channels"),
        "sample_rate": sample_rate,
        "faststart": True,
        "atoms": atoms,
    }, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python scripts/verify_video_media.py <video.mp4> [<video2.mp4> ...]")
    for argument in sys.argv[1:]:
        try:
            validate(Path(argument).expanduser())
        except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            print(f"ERRO: {argument}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
