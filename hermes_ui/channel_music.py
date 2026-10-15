"""Música de fundo anexada por canal, com rodízio circular entre vídeos.

0.9.99: o dropdown "Fonte da música de fundo" oferecia "Carregar ficheiro"
mas nenhum dos dois locais (card do canal em Canais YouTube e Configurações
de áudio na Criação de Vídeos) renderizava um uploader — a opção não fazia
nada. Este módulo centraliza o componente partilhado de upload e toda a
persistência em disco:

storage/blueprints/canais/{channel_id}/music/
    ├── manifest.json
    ├── trilha1.mp3
    └── trilha2.mp3

O escopo "video_creation" (Criação de Vídeos sem canal vinculado) usa
storage/blueprints/video_creation/music/ com o mesmo layout de manifest.

O manifest é a fonte da verdade do rodízio: ``rotation_enabled`` liga a
selecção circular e ``last_used_index`` guarda a última faixa entregue ao
pipeline. O índice é avançado e persistido ANTES de qualquer renderização,
para que a morte do worker nunca faça o mesmo vídeo repetir a mesma faixa.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from . import storage

MUSIC_UPLOAD_EXTENSIONS = (".mp3", ".wav", ".m4a", ".ogg", ".flac")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
VIDEO_CREATION_SCOPE = "video_creation"
CHANNEL_SCOPE_PREFIX = "channel_"

_WINDOWS_RESERVED_STEMS = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)}
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def music_scope_for_channel(channel_id: str) -> str:
    """Escopo de armazenamento: pasta do canal quando existe, senão a área global."""
    cleaned = str(channel_id or "").strip()
    return f"{CHANNEL_SCOPE_PREFIX}{cleaned}" if cleaned else VIDEO_CREATION_SCOPE


def _safe_scope_segment(scope: str) -> str:
    """Segmento de pasta seguro para o escopo (ids são hex, mas sanitiza sempre)."""
    segment = re.sub(r"[^\w\-. ]+", "_", str(scope or "").strip(), flags=re.UNICODE).strip(" .")
    if not segment or segment in {".", ".."} or segment.upper() in _WINDOWS_RESERVED_STEMS:
        return "sem-canal"
    return segment


def _music_directory(scope: str, *, create: bool) -> Path:
    """Pasta física das músicas do escopo (canal ou criação de vídeo global)."""
    scope = str(scope or "").strip() or VIDEO_CREATION_SCOPE
    if scope.startswith(CHANNEL_SCOPE_PREFIX):
        base = storage.BLUEPRINTS / "canais" / _safe_scope_segment(scope.removeprefix(CHANNEL_SCOPE_PREFIX))
    else:
        base = storage.BLUEPRINTS / "video_creation"
    directory = base / "music"
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def music_directory(scope: str) -> Path:
    return _music_directory(scope, create=True)


def manifest_path(scope: str) -> Path:
    return _music_directory(scope, create=False) / "manifest.json"


def read_music_manifest(scope: str) -> dict[str, Any]:
    """Ler o manifest normalizado; ficheiro em falta/corrompido devolve o padrão."""
    normalized: dict[str, Any] = {"musics": [], "rotation_enabled": False, "last_used_index": 0}
    path = manifest_path(scope)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return normalized
    if not isinstance(data, dict):
        return normalized
    musics = data.get("musics")
    normalized["musics"] = [dict(item) for item in musics if isinstance(item, dict)] if isinstance(musics, list) else []
    normalized["rotation_enabled"] = bool(data.get("rotation_enabled", False))
    raw_index = data.get("last_used_index", 0)
    try:
        normalized["last_used_index"] = max(0, int(raw_index))
    except (TypeError, ValueError):
        normalized["last_used_index"] = 0
    return normalized


def _write_music_manifest(scope: str, manifest: dict[str, Any]) -> None:
    storage.atomic_write(manifest_path(scope), manifest)


def list_channel_musics(scope: str) -> list[dict[str, Any]]:
    """Músicas anexadas ao escopo, cada uma com o caminho físico em disco."""
    manifest = read_music_manifest(scope)
    directory = _music_directory(scope, create=False)
    musics: list[dict[str, Any]] = []
    for item in manifest["musics"]:
        entry = dict(item)
        entry["path"] = str(directory / str(entry.get("filename") or ""))
        musics.append(entry)
    return musics


def sanitize_music_filename(name: str) -> str:
    """Nome de ficheiro seguro: sem traversal, sem caracteres inválidos, extensão suportada."""
    raw = str(name or "").replace("\\", "/").split("/")[-1]
    stem = re.sub(r"[^\w\-. ]+", "_", Path(raw).stem, flags=re.UNICODE).strip(" ._")
    if not stem or stem in {".", ".."} or stem.upper() in _WINDOWS_RESERVED_STEMS:
        stem = f"musica_{stem or uuid.uuid4().hex[:6]}"
    suffix = Path(raw).suffix.lower()
    if suffix not in MUSIC_UPLOAD_EXTENSIONS:
        suffix = ".mp3"
    return f"{stem}{suffix}"


def _unique_target(directory: Path, filename: str) -> Path:
    """Destino sem sobrescrever: trilha1.mp3 → trilha1_2.mp3 → trilha1_3.mp3…"""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for counter in range(2, 1000):
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def checksum_bytes(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


def save_channel_music(scope: str, filename: str, content: bytes) -> dict[str, Any]:
    """Persistir imediatamente um upload na pasta do escopo e no manifest.

    Duplicados são detectados por checksum: reenviar o mesmo ficheiro devolve
    a entrada existente sem duplicar bytes em disco.
    """
    if not content:
        raise ValueError("O ficheiro de música está vazio.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Ficheiro demasiado grande ({format_file_size(len(content))}). Tamanho máx: 50 MB por arquivo.")
    checksum = checksum_bytes(content)
    manifest = read_music_manifest(scope)
    for existing in manifest["musics"]:
        if str(existing.get("checksum") or "") == checksum:
            entry = dict(existing)
            entry["path"] = str(_music_directory(scope, create=False) / str(entry.get("filename") or ""))
            return entry
    safe_name = sanitize_music_filename(filename)
    target = _unique_target(music_directory(scope), safe_name)
    target.write_bytes(content)
    entry = {
        "id": uuid.uuid4().hex,
        "filename": target.name,
        "size": len(content),
        "checksum": checksum,
        "uploaded_at": now(),
        "path": str(target),
    }
    manifest["musics"].append({key: value for key, value in entry.items() if key != "path"})
    _write_music_manifest(scope, manifest)
    return entry


def remove_channel_music(scope: str, music_id: str) -> bool:
    """Apagar o ficheiro físico e a entrada do manifest; devolve True se removeu."""
    manifest = read_music_manifest(scope)
    remaining = [item for item in manifest["musics"] if str(item.get("id") or "") != str(music_id)]
    if len(remaining) == len(manifest["musics"]):
        return False
    removed = next(item for item in manifest["musics"] if str(item.get("id") or "") == str(music_id))
    try:
        (music_directory(scope) / str(removed.get("filename") or "")).unlink(missing_ok=True)
    except OSError:
        pass
    manifest["musics"] = remaining
    manifest["last_used_index"] = min(int(manifest.get("last_used_index") or 0), max(0, len(remaining) - 1))
    _write_music_manifest(scope, manifest)
    return True


def set_rotation_enabled(scope: str, enabled: bool) -> None:
    manifest = read_music_manifest(scope)
    manifest["rotation_enabled"] = bool(enabled)
    _write_music_manifest(scope, manifest)


def select_music_for_render(scope: str) -> dict[str, Any] | None:
    """Escolher a faixa para o próximo vídeo, avançando o rodízio em círculo.

    Com rodízio activo e 2+ músicas, devolve a PRÓXIMA faixa —
    (last_used_index + 1) % len(musics) — e persiste o novo índice ANTES de
    devolver, para que a queda do worker nunca repita a mesma faixa no vídeo
    seguinte. Sem rodízio, usa sempre a primeira música (determinístico).
    """
    manifest = read_music_manifest(scope)
    musics = manifest["musics"]
    if not musics:
        return None
    directory = _music_directory(scope, create=False)
    if bool(manifest.get("rotation_enabled")) and len(musics) >= 2:
        next_index = (int(manifest.get("last_used_index") or 0) + 1) % len(musics)
        manifest["last_used_index"] = next_index
        _write_music_manifest(scope, manifest)
        selected = dict(musics[next_index])
    else:
        selected = dict(musics[0])
    selected["path"] = str(directory / str(selected.get("filename") or ""))
    return selected


def format_file_size(size_bytes: int) -> str:
    """Tamanho legível (KB/MB) para a lista de músicas anexadas."""
    size = max(0, int(size_bytes or 0))
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def render_music_upload_section(
    scope: str,
    current_musics: list[dict[str, Any]] | None = None,
    *,
    volume: int | None = None,
) -> dict[str, Any]:
    """Uploader + lista de músicas anexadas + checkbox de rodízio (partilhado).

    Usado tanto no card do canal (Configurações de Audio) como na Criação de
    Vídeos (Configurações de áudio). O volume da música NÃO é renderizado
    aqui — permanece no chamador, sem alteração de comportamento.

    Devolve o estado actualizado:
        {"source": "Carregar ficheiro", "musics": [...], "rotation_enabled": bool, "volume": int|None}
    """
    state: dict[str, Any] = {"source": "Carregar ficheiro", "musics": [], "rotation_enabled": False, "volume": volume}
    musics = list_channel_musics(scope)
    if not musics and current_musics:
        musics = [dict(item) for item in current_musics]

    uploaded_files = st.file_uploader(
        "Carregar música de fundo",
        type=["mp3", "wav", "m4a", "ogg", "flac"],
        accept_multiple_files=True,
        key=f"music_upload_{scope}",
        help="Formatos aceitos: MP3, WAV, M4A, OGG, FLAC. Tamanho máx: 50 MB por arquivo.",
    )
    saved_names: list[str] = []
    if uploaded_files:
        known_checksums = {str(item.get("checksum") or "") for item in musics}
        for uploaded in uploaded_files:
            try:
                content = uploaded.getvalue()
                if checksum_bytes(content) in known_checksums:
                    continue
                entry = save_channel_music(scope, uploaded.name, content)
                saved_names.append(str(entry.get("filename") or ""))
                known_checksums.add(str(entry.get("checksum") or ""))
            except (OSError, ValueError) as exc:
                st.error(f"{uploaded.name}: {exc}")
        if saved_names:
            st.success(f"{len(saved_names)} música(s) guardada(s): {', '.join(saved_names)}")
        musics = list_channel_musics(scope)

    st.markdown(f"🎵 **Músicas anexadas ({len(musics)})**")
    if not musics:
        st.caption("Nenhuma música anexada.")
    for index, music in enumerate(musics, start=1):
        music_id = str(music.get("id") or "")
        confirm_key = f"music_remove_confirm_{scope}_{music_id}"
        row = st.columns([4.1, 1.2])
        with row[0]:
            st.caption(f"{index}. **{music.get('filename', 'ficheiro')}** ({format_file_size(int(music.get('size') or 0))})")
        with row[1]:
            if st.button("🗑️ Remover", key=f"music_remove_{scope}_{music_id}"):
                st.session_state[confirm_key] = True
        if st.session_state.get(confirm_key):
            st.warning(f"Apagar \"{music.get('filename', 'ficheiro')}\" do disco?")
            confirm_cols = st.columns(2)
            removed = False
            if confirm_cols[0].button("Confirmar", key=f"music_remove_yes_{scope}_{music_id}", type="primary"):
                remove_channel_music(scope, music_id)
                st.session_state.pop(confirm_key, None)
                removed = True
            if confirm_cols[1].button("Cancelar", key=f"music_remove_no_{scope}_{music_id}"):
                st.session_state.pop(confirm_key, None)
                removed = True
            if removed:
                st.rerun()
            return state

    rotation_enabled = False
    if len(musics) >= 2:
        manifest = read_music_manifest(scope)
        rotation_enabled = st.checkbox(
            "Fazer rodízio entre as músicas a cada vídeo gerado",
            value=bool(manifest.get("rotation_enabled")),
            key=f"rotation_{scope}",
            help="Cada novo vídeo usará a próxima música da lista, em ordem circular.",
        )
        if rotation_enabled != bool(manifest.get("rotation_enabled")):
            set_rotation_enabled(scope, rotation_enabled)

    state["musics"] = musics
    state["rotation_enabled"] = rotation_enabled
    return state


__all__ = [
    "MAX_UPLOAD_BYTES",
    "MUSIC_UPLOAD_EXTENSIONS",
    "VIDEO_CREATION_SCOPE",
    "format_file_size",
    "list_channel_musics",
    "manifest_path",
    "music_directory",
    "music_scope_for_channel",
    "read_music_manifest",
    "remove_channel_music",
    "render_music_upload_section",
    "sanitize_music_filename",
    "save_channel_music",
    "select_music_for_render",
    "set_rotation_enabled",
]
