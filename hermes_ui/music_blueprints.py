from __future__ import annotations

import re
import shutil
import os
import tempfile
from pathlib import Path

from .storage import ROOT, STORAGE


SEED_MUSIC_BLUEPRINTS = ROOT / "seed" / "blueprints" / "music"
MUSIC_BLUEPRINTS = STORAGE / "blueprints" / "music"


def _safe_name(value: str) -> str:
    raw = str(value or "").replace("/", "-").replace("\\", "-")
    stem = re.sub(r"[^\w\-. À-ÿ]+", "-", Path(raw).stem, flags=re.UNICODE).strip(" .-")
    return stem or "music-blueprint"


def music_blueprint_directory() -> Path:
    MUSIC_BLUEPRINTS.mkdir(parents=True, exist_ok=True)
    return MUSIC_BLUEPRINTS


def seed_music_blueprints() -> int:
    """Copy packaged Markdown seeds without overwriting user documents."""
    if not SEED_MUSIC_BLUEPRINTS.is_dir():
        return 0
    destination = music_blueprint_directory()
    copied = 0
    for source in sorted(SEED_MUSIC_BLUEPRINTS.glob("*.md")):
        target = destination / source.name
        if not target.exists():
            shutil.copy2(source, target)
            copied += 1
    return copied


def list_music_blueprint_documents() -> list[Path]:
    directory = music_blueprint_directory()
    return sorted(directory.glob("*.md"), key=lambda path: (path.name.casefold(), path.name))


def read_music_blueprint(path: Path) -> str:
    if path.parent.resolve() != MUSIC_BLUEPRINTS.resolve():
        raise ValueError("Music Blueprint fora da biblioteca local.")
    return path.read_text(encoding="utf-8")


def save_music_blueprint(name: str, content: str) -> Path:
    clean_name = str(name or "").strip()
    clean_content = str(content or "").strip()
    if not clean_name:
        raise ValueError("Informe o nome do Music Blueprint antes de guardar.")
    if not clean_content:
        raise ValueError("O gerador não devolveu conteúdo Markdown para guardar.")
    target = music_blueprint_directory() / f"{_safe_name(clean_name)}.md"
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(clean_content + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return target
