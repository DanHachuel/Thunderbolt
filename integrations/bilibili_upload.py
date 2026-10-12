"""Upload de vídeo para Bilibili usando bilibili-api-python.

A biblioteca é opcional no import para que o Thunderbolt continue a arrancar sem
credenciais Bilibili. As operações do SDK são assíncronas; este adapter expõe uma
interface síncrona adequada à UI Streamlit e nunca devolve os cookies nos dados.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Awaitable

from .platforms import IntegrationResult

BILIBILI_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
BILIBILI_MAX_TITLE = 80
BILIBILI_MAX_DESCRIPTION = 2000
BILIBILI_MAX_TAGS = 10
BILIBILI_DEFAULT_TID = 130
BILIBILI_API_VERSION = "17.4.2"
_SENSITIVE_FIELDS = {"sessdata", "bili_jct", "buvid3", "buvid4", "dedeuserid", "ac_time_value", "proxy"}


def _safe_card(card: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": str(card.get("id") or f"bilibili-api-{index + 1}").strip(),
        "label": str(card.get("label") or card.get("name") or f"Conta Bilibili {index + 1}").strip(),
        "active": bool(card.get("active", True)),
        "sessdata": str(card.get("sessdata") or "").strip(),
        "bili_jct": str(card.get("bili_jct") or "").strip(),
        "buvid3": str(card.get("buvid3") or "").strip(),
        "buvid4": str(card.get("buvid4") or "").strip(),
        "dedeuserid": str(card.get("dedeuserid") or "").strip(),
        "ac_time_value": str(card.get("ac_time_value") or "").strip(),
        "proxy": str(card.get("proxy") or "").strip(),
    }


def normalise_bilibili_api_cards(settings: dict[str, Any] | None) -> tuple[list[dict[str, Any]], bool]:
    """Normalise multi-account cards and migrate one legacy settings record."""
    settings = settings or {}
    raw = settings.get("bilibili_api_cards")
    cards: list[dict[str, Any]] = []
    changed = not isinstance(raw, list)
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if isinstance(item, dict):
                card = _safe_card(item, index)
                cards.append(card)
                if any(str(item.get(key) or "").strip() != str(card.get(key) or "").strip() for key in card if key not in {"active"}):
                    changed = True
            else:
                changed = True
    legacy_keys = ("bilibili_sessdata", "bilibili_bili_jct", "bilibili_buvid3", "bilibili_buvid4", "bilibili_dedeuserid", "bilibili_ac_time_value", "bilibili_proxy")
    legacy_values = {key.removeprefix("bilibili_"): str(settings.get(key) or "").strip() for key in legacy_keys}
    if not cards and any(legacy_values.values()):
        cards.append(_safe_card({"id": "bilibili-api-1", "label": "Conta Bilibili 1", **legacy_values}, 0))
        changed = True
    return cards, changed


def _redacted_card(card: dict[str, Any]) -> dict[str, Any]:
    return {key: ("***" if key in _SENSITIVE_FIELDS and value else value) for key, value in card.items() if key not in _SENSITIVE_FIELDS or not value}


def _safe_card_payload(card: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in _safe_card(card, 0).items() if key != "id"}


def _import_sdk() -> tuple[Any, Any]:
    try:
        from bilibili_api import Credential, video_uploader
    except ImportError as exc:
        raise RuntimeError("A dependência bilibili-api-python não está instalada. Instale/actualize o Thunderbolt e tente novamente.") from exc
    return Credential, video_uploader


def _run_async(awaitable: Awaitable[Any]) -> Any:
    """Run one SDK coroutine from Streamlit, including when a loop already exists."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    result: list[Any] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(awaitable))
        except BaseException as exc:  # preserve SDK exception for UI attribution
            error.append(exc)

    thread = threading.Thread(target=runner, name="thunderbolt-bilibili-sdk", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0] if result else None


def _credential(card: dict[str, Any], Credential: Any) -> Any:
    values = _safe_card_payload(card)
    values.pop("label", None)
    values.pop("active", None)
    values.pop("proxy", None)
    return Credential(proxy=str(card.get("proxy") or "").strip() or None, **values)


def _derive_cover(video_path: Path, directory: Path) -> Path:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        executable = get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("Não foi possível localizar FFmpeg para criar a capa automática do vídeo Bilibili.") from exc
    target = directory / "bilibili-cover.jpg"
    completed = subprocess.run(
        [executable, "-y", "-hide_banner", "-loglevel", "error", "-ss", "0", "-i", str(video_path), "-frames:v", "1", "-q:v", "3", str(target)],
        capture_output=True, text=True, timeout=90, check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if completed.returncode != 0 or not target.is_file():
        raise RuntimeError("FFmpeg não conseguiu criar uma capa a partir do vídeo Bilibili.")
    return target

def _normalise_tags(tags: str | list[str] | tuple[str, ...] | None) -> list[str]:
    values = tags if isinstance(tags, (list, tuple)) else str(tags or "").replace("\n", ",").split(",")
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            output.append(clean)
            seen.add(clean)
    return output


class BilibiliApiAdapter:
    """Synchronous wrapper around bilibili-api-python's asynchronous video uploader."""

    def __init__(self, card: dict[str, Any] | None = None, settings: dict[str, Any] | None = None):
        self.card = _safe_card(card or {}, 0)
        self.settings = settings or {}

    def status(self) -> IntegrationResult:
        missing = [field for field in ("sessdata", "bili_jct", "buvid3") if not str(self.card.get(field) or "").strip()]
        if missing:
            return IntegrationResult(False, "Conta Bilibili incompleta: configure SESSDATA, bili_jct e BUVID3.", {"missing_fields": missing, "account": self.card.get("label", "Conta Bilibili")})
        try:
            _import_sdk()
        except RuntimeError as exc:
            return IntegrationResult(False, str(exc), {"account": self.card.get("label", "Conta Bilibili")})
        return IntegrationResult(True, f"Conta Bilibili pronta: {self.card.get('label', 'Conta Bilibili')}.", {"account": self.card.get("label", "Conta Bilibili"), "sdk": BILIBILI_API_VERSION})

    def test_connection(self) -> IntegrationResult:
        status = self.status()
        if not status.ok:
            return status
        try:
            Credential, _ = _import_sdk()
            credential = _credential(self.card, Credential)
            valid = _run_async(credential.check_valid())
            if not bool(valid):
                return IntegrationResult(False, "A sessão Bilibili foi rejeitada ou expirou. Actualize SESSDATA, bili_jct e BUVID3.", {"account": self.card.get("label", "Conta Bilibili"), "valid": False})
            return IntegrationResult(True, f"Chamada Bilibili concluída para {self.card.get('label', 'Conta Bilibili')}.", {"account": self.card.get("label", "Conta Bilibili"), "valid": True})
        except Exception as exc:
            return IntegrationResult(False, f"A chamada Bilibili falhou: {exc}", {"account": self.card.get("label", "Conta Bilibili"), "api": "bilibili-api-python"})

    def upload_video(
        self,
        video_path: str | Path,
        *,
        title: str,
        description: str = "",
        tags: str | list[str] | tuple[str, ...] | None = None,
        tid: int = BILIBILI_DEFAULT_TID,
        cover_path: str | Path | None = None,
        original: bool = True,
        dynamic: str = "",
    ) -> IntegrationResult:
        status = self.status()
        if not status.ok:
            return status
        path = Path(video_path).expanduser()
        if not path.is_file():
            return IntegrationResult(False, f"Vídeo Bilibili não encontrado: {path}", {"api": "bilibili-api-python"})
        if path.suffix.lower() not in BILIBILI_VIDEO_EXTENSIONS:
            return IntegrationResult(False, f"Formato Bilibili não suportado: {path.suffix}. Use MP4, MOV, MKV ou WEBM.", {"api": "bilibili-api-python"})
        clean_title = str(title or "Vídeo Thunderbolt").strip()
        clean_description = str(description or "").strip()
        clean_tags = _normalise_tags(tags)
        if not clean_title or len(clean_title) > BILIBILI_MAX_TITLE:
            return IntegrationResult(False, "O título Bilibili é obrigatório e deve ter no máximo 80 caracteres.", {"api": "bilibili-api-python"})
        if len(clean_description) > BILIBILI_MAX_DESCRIPTION:
            return IntegrationResult(False, "A descrição Bilibili deve ter no máximo 2000 caracteres.", {"api": "bilibili-api-python"})
        if not clean_tags or len(clean_tags) > BILIBILI_MAX_TAGS:
            return IntegrationResult(False, "Indique entre 1 e 10 tags Bilibili, separadas por vírgulas.", {"api": "bilibili-api-python"})
        try:
            tid_value = int(tid)
        except (TypeError, ValueError):
            return IntegrationResult(False, "O ID da secção Bilibili deve ser numérico.", {"api": "bilibili-api-python"})
        cover = Path(cover_path).expanduser() if cover_path else None
        if cover is not None and not cover.is_file():
            return IntegrationResult(False, f"Capa Bilibili não encontrada: {cover}", {"api": "bilibili-api-python"})
        try:
            Credential, video_uploader = _import_sdk()
            credential = _credential(self.card, Credential)
            page = video_uploader.VideoUploaderPage(str(path), clean_title, clean_description)
            meta: dict[str, Any] = {
                "title": clean_title,
                "copyright": 1 if original else 2,
                "tid": tid_value,
                "tag": ",".join(clean_tags),
                "desc_format_id": 9999,
                "desc": clean_description,
                "recreate": -1,
                "dynamic": str(dynamic or "")[:233],
                "interactive": 0,
                "act_reserve_create": 0,
                "no_disturbance": 0,
                "no_reprint": 0,
                "subtitle": {"open": 0, "lan": ""},
                "dolby": 0,
                "lossless_music": 0,
                "web_os": 1,
            }
            temporary_cover: tempfile.TemporaryDirectory[str] | None = None
            if cover is None:
                temporary_cover = tempfile.TemporaryDirectory(prefix="thunderbolt-bilibili-")
                cover = _derive_cover(path, Path(temporary_cover.name))
            try:
                uploader = video_uploader.VideoUploader([page], meta, credential, cover=str(cover))
                result = _run_async(uploader.start())
            finally:
                if temporary_cover is not None:
                    temporary_cover.cleanup()
            payload = result if isinstance(result, dict) else {"response": result}
            public_data = {key: payload.get(key) for key in ("bvid", "aid", "code", "message") if key in payload}
            public_data.update({"account": self.card.get("label", "Conta Bilibili"), "api": "bilibili-api-python", "title": clean_title})
            bvid = str(payload.get("bvid") or "").strip()
            message = "Upload Bilibili concluído."
            if bvid:
                message += f" BVID: {bvid}."
            return IntegrationResult(True, message, public_data)
        except Exception as exc:
            return IntegrationResult(False, f"Upload Bilibili falhou na API bilibili-api-python: {exc}", {"account": self.card.get("label", "Conta Bilibili"), "api": "bilibili-api-python"})


__all__ = [
    "BILIBILI_API_VERSION",
    "BILIBILI_DEFAULT_TID",
    "BILIBILI_MAX_DESCRIPTION",
    "BILIBILI_MAX_TAGS",
    "BILIBILI_MAX_TITLE",
    "BILIBILI_VIDEO_EXTENSIONS",
    "BilibiliApiAdapter",
    "normalise_bilibili_api_cards",
]
