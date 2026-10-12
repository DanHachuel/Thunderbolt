"""Music upload integrations used by the Thunderbolt Upload Música page.

The adapters deliberately keep provider-specific behaviour behind the existing
IntegrationResult contract. They never log or return secrets and they do not
perform a remote write from a credential-validation call.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests

from .platforms import IntegrationResult


MUSIC_UPLOAD_EXTENSIONS = {".mp3", ".m4a", ".wma", ".flac", ".ogg", ".wav", ".aac"}
YT_MUSIC_UPLOAD_EXTENSIONS = {".mp3", ".m4a", ".wma", ".flac", ".ogg"}
DEFAULT_JEWELMUSIC_BASE_URL = "https://api.jewelmusic.com"
DEFAULT_JEWELMUSIC_TIMEOUT = 120
DEFAULT_YTMUSICAPI_TIMEOUT = 240
DEFAULT_PUSHTUNES_TIMEOUT = 1800
PUSHTUNES_SOURCES = ("subsonic", "jellyfin", "csv", "spotify", "ytm")
PUSHTUNES_TARGETS = ("spotify", "ytm", "tidal", "csv")
PUSHTUNES_OPERATIONS = ("tracks", "albums", "playlist")


def _bounded_timeout(value: Any, default: int, maximum: int) -> int:
    try:
        return max(5, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _proxy_kwargs(proxy_url: str) -> dict[str, dict[str, str]]:
    proxy = str(proxy_url or "").strip()
    return {"proxies": {"http": proxy, "https": proxy}} if proxy else {}


def _audio_path(value: str | Path, allowed_extensions: set[str] | None = None) -> tuple[Path | None, str | None]:
    path = Path(value).expanduser() if str(value or "").strip() else Path("")
    if not path.is_file():
        return None, f"Ficheiro de música não encontrado: {path}"
    if path.stat().st_size <= 0:
        return None, f"O ficheiro de música está vazio: {path.name}"
    extensions = allowed_extensions or MUSIC_UPLOAD_EXTENSIONS
    if path.suffix.lower() not in extensions:
        allowed = ", ".join(sorted(extensions))
        return None, f"Formato não suportado para este destino: {path.suffix or '(sem extensão)'}. Use {allowed}."
    return path, None


def _response_payload(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"text": response.text[:2000]}


def _redact_output(text: str, secrets: list[str]) -> str:
    result = str(text or "")
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[redacted]")
    return result[-8000:]


def _error(message: str, data: dict[str, Any] | None = None) -> IntegrationResult:
    return IntegrationResult(False, message, data or {})


class JewelMusicAdapter:
    """Client for JewelMusic's documented ``POST /v1/tracks/upload`` API.

    The public GitHub repository currently documents the Python SDK but does
    not publish ``jewelmusic-sdk`` on PyPI. Thunderbolt therefore mirrors the
    SDK's documented HTTP contract with requests instead of adding an
    unavailable dependency.
    """

    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or {}
        self.enabled = bool(self.settings.get("jewelmusic_enabled", False))
        self.api_key = str(self.settings.get("jewelmusic_api_key") or "").strip()
        self.base_url = str(self.settings.get("jewelmusic_base_url") or DEFAULT_JEWELMUSIC_BASE_URL).strip().rstrip("/")
        self.timeout = _bounded_timeout(self.settings.get("jewelmusic_timeout_seconds"), DEFAULT_JEWELMUSIC_TIMEOUT, 900)
        self.proxy_url = str(self.settings.get("jewelmusic_proxy_url") or "").strip()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/v1/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "Thunderbolt-JewelMusic/0.3",
        }

    def status(self) -> IntegrationResult:
        if not self.enabled:
            return _error("JewelMusic está desactivado nesta subaba.", {"status": "disabled"})
        if not self.api_key:
            return _error("JewelMusic não está configurado: introduza a API Key.", {"status": "missing_api_key"})
        if not self.base_url.startswith(("http://", "https://")):
            return _error("A Base URL JewelMusic deve começar por http:// ou https://.", {"status": "invalid_base_url"})
        return IntegrationResult(True, "JewelMusic configurado.", {"base_url": self.base_url, "api_key_configured": True})

    def test_connection(self) -> IntegrationResult:
        status = self.status()
        if not status.ok:
            return status
        try:
            response = requests.get(self._url("ping"), headers=self._headers(), timeout=self.timeout, **_proxy_kwargs(self.proxy_url))
        except requests.RequestException as exc:
            return _error(f"Não foi possível contactar o JewelMusic: {exc}", {"status": "network_error"})
        payload = _response_payload(response)
        if response.status_code >= 400:
            return _error(f"JewelMusic rejeitou a validação (HTTP {response.status_code}).", {"status_code": response.status_code, "payload": payload})
        return IntegrationResult(True, "Ligação JewelMusic validada sem criar uma track.", {"status_code": response.status_code, "payload": payload})

    def upload_track(self, audio_path: str | Path, *, title: str, artist: str, album: str = "", year: str = "", genre: str = "") -> IntegrationResult:
        status = self.status()
        if not status.ok:
            return status
        path, error = _audio_path(audio_path)
        if error or path is None:
            return _error(error or "Ficheiro de música inválido.")
        clean_title = str(title or "").strip() or path.stem
        clean_artist = str(artist or "").strip()
        if not clean_artist:
            return _error("Indique o artista antes de enviar para o JewelMusic.")
        metadata = {
            "title": clean_title,
            "artist": clean_artist,
            "album": str(album or "").strip(),
            "year": str(year or "").strip(),
            "genre": str(genre or "").strip(),
        }
        metadata = {key: value for key, value in metadata.items() if value}
        content_type = mimetypes.guess_type(path.name)[0] or "audio/mpeg"
        try:
            with path.open("rb") as handle:
                response = requests.post(
                    self._url("tracks/upload"),
                    headers=self._headers(),
                    data=metadata,
                    files={"file": (path.name, handle, content_type)},
                    timeout=self.timeout,
                    **_proxy_kwargs(self.proxy_url),
                )
        except requests.RequestException as exc:
            return _error(f"Não foi possível enviar a música para o JewelMusic: {exc}", {"filename": path.name})
        payload = _response_payload(response)
        if response.status_code >= 400:
            return _error(f"JewelMusic rejeitou a música (HTTP {response.status_code}).", {"filename": path.name, "status_code": response.status_code, "payload": payload})
        return IntegrationResult(True, f"Música enviada para o JewelMusic: {clean_title}.", {"filename": path.name, "title": clean_title, "artist": clean_artist, "payload": payload, "status_code": response.status_code})


class YTMusicApiAdapter:
    """Adapter around ytmusicapi's browser-authenticated upload_song method."""

    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or {}
        self.enabled = bool(self.settings.get("ytmusicapi_enabled", False))
        self.auth_file = str(self.settings.get("ytmusicapi_auth_file") or "").strip()
        self.proxy_url = str(self.settings.get("ytmusicapi_proxy_url") or "").strip()
        self.timeout = _bounded_timeout(self.settings.get("ytmusicapi_timeout_seconds"), DEFAULT_YTMUSICAPI_TIMEOUT, 900)

    def _auth_path(self) -> Path:
        return Path(self.auth_file).expanduser()

    def status(self) -> IntegrationResult:
        if not self.enabled:
            return _error("ytmusicapi está desactivado nesta subaba.", {"status": "disabled"})
        if not self.auth_file:
            return _error("ytmusicapi não está configurado: indique o caminho do browser.json.", {"status": "missing_auth_file"})
        path = self._auth_path()
        if not path.is_file():
            return _error(f"Ficheiro de autenticação ytmusicapi não encontrado: {path}", {"status": "missing_auth_file", "path": str(path)})
        try:
            from ytmusicapi import YTMusic  # type: ignore
        except ImportError:
            return _error("A dependência ytmusicapi não está instalada. Execute novamente a instalação do Thunderbolt.", {"status": "dependency_missing"})
        try:
            YTMusic(str(path), proxies=_proxy_kwargs(self.proxy_url).get("proxies"))
        except Exception as exc:
            return _error(f"O browser.json não foi aceite pelo ytmusicapi: {exc}", {"status": "invalid_auth_file", "path": str(path)})
        return IntegrationResult(True, "ytmusicapi pronto com autenticação de browser.", {"auth_file": str(path), "auth_type": "browser"})

    def _client(self):
        from ytmusicapi import YTMusic  # type: ignore

        return YTMusic(str(self._auth_path()), proxies=_proxy_kwargs(self.proxy_url).get("proxies"))

    def test_connection(self) -> IntegrationResult:
        status = self.status()
        if not status.ok:
            return status
        try:
            songs = self._client().get_library_upload_songs(limit=1)
        except Exception as exc:
            return _error(f"Não foi possível consultar a biblioteca de uploads do YouTube Music: {exc}", {"status": "network_or_auth_error"})
        count = len(songs) if isinstance(songs, list) else 0
        return IntegrationResult(True, "Autenticação ytmusicapi validada com consulta read-only.", {"sample_count": count})

    def upload_song(self, audio_path: str | Path) -> IntegrationResult:
        status = self.status()
        if not status.ok:
            return status
        path, error = _audio_path(audio_path, YT_MUSIC_UPLOAD_EXTENSIONS)
        if error or path is None:
            return _error(error or "Ficheiro de música inválido.")
        if path.stat().st_size >= 300 * 1024 * 1024:
            return _error("O YouTube Music não aceita uploads com 300 MB ou mais.", {"filename": path.name})
        try:
            result = self._client().upload_song(str(path))
        except Exception as exc:
            return _error(f"Não foi possível enviar a música para o YouTube Music: {exc}", {"filename": path.name})
        result_name = str(getattr(result, "name", result))
        if "SUCCEEDED" not in result_name.upper():
            data: dict[str, Any] = {"filename": path.name, "result": result_name}
            if hasattr(result, "status_code"):
                data["status_code"] = result.status_code
            return _error(f"O YouTube Music não confirmou o upload de {path.name}.", data)
        return IntegrationResult(True, f"Música enviada para o YouTube Music: {path.stem}.", {"filename": path.name, "result": result_name})


class PushtunesAdapter:
    """Safe wrapper around the Pushtunes CLI library synchronizer.

    Pushtunes moves library metadata between local sources and Spotify, YTM or
    Tidal. It does not upload arbitrary local MP3 bytes, so the UI exposes the
    supported source/target sync operations instead of mislabelling them as a
    single-file upload.
    """

    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or {}
        self.enabled = bool(self.settings.get("pushtunes_enabled", False))
        self.executable = str(self.settings.get("pushtunes_executable") or "pushtunes").strip()
        self.source = str(self.settings.get("pushtunes_source") or "csv").strip().lower()
        self.target = str(self.settings.get("pushtunes_target") or "ytm").strip().lower()
        self.operation = str(self.settings.get("pushtunes_operation") or "tracks").strip().lower()
        self.profile = str(self.settings.get("pushtunes_profile") or "").strip()
        self.csv_file = str(self.settings.get("pushtunes_csv_file") or "").strip()
        self.ytm_auth_file = str(self.settings.get("pushtunes_ytm_auth_file") or "").strip()
        self.tidal_session_file = str(self.settings.get("pushtunes_tidal_session_file") or "").strip()
        self.playlist_name = str(self.settings.get("pushtunes_playlist_name") or "").strip()
        self.similarity = self.settings.get("pushtunes_similarity", 0.8)
        self.working_directory = str(self.settings.get("pushtunes_working_directory") or "").strip()
        self.spotify_client_id = str(self.settings.get("pushtunes_spotify_client_id") or "").strip()
        self.spotify_client_secret = str(self.settings.get("pushtunes_spotify_client_secret") or "").strip()
        self.spotify_redirect_uri = str(self.settings.get("pushtunes_spotify_redirect_uri") or "").strip()
        self.timeout = _bounded_timeout(self.settings.get("pushtunes_timeout_seconds"), DEFAULT_PUSHTUNES_TIMEOUT, 3600)

    def _command_prefix(self) -> list[str] | None:
        if Path(self.executable).expanduser().is_file() or shutil.which(self.executable):
            return [str(Path(self.executable).expanduser())] if Path(self.executable).expanduser().is_file() else [self.executable]
        if self.executable == "pushtunes":
            try:
                import importlib.util

                if importlib.util.find_spec("pushtunes") is not None:
                    return [sys.executable, "-m", "pushtunes.cli.main"]
            except (ImportError, ValueError):
                pass
        return None

    def status(self) -> IntegrationResult:
        if not self.enabled:
            return _error("Pushtunes está desactivado nesta subaba.", {"status": "disabled"})
        prefix = self._command_prefix()
        if prefix is None:
            return _error("Pushtunes não está instalado ou o executável não foi encontrado. Execute novamente a instalação do Thunderbolt.", {"status": "executable_missing", "executable": self.executable})
        if self.source not in PUSHTUNES_SOURCES:
            return _error(f"Fonte Pushtunes inválida: {self.source}.", {"status": "invalid_source", "allowed": list(PUSHTUNES_SOURCES)})
        if self.target not in PUSHTUNES_TARGETS:
            return _error(f"Destino Pushtunes inválido: {self.target}.", {"status": "invalid_target", "allowed": list(PUSHTUNES_TARGETS)})
        if self.operation not in PUSHTUNES_OPERATIONS:
            return _error(f"Operação Pushtunes inválida: {self.operation}.", {"status": "invalid_operation", "allowed": list(PUSHTUNES_OPERATIONS)})
        if self.profile and not Path(self.profile).expanduser().is_file():
            return _error(f"Perfil Pushtunes não encontrado: {self.profile}", {"status": "missing_profile"})
        if self.source == "csv" and not self.csv_file:
            return _error("Indique um CSV de origem quando a fonte Pushtunes for csv.", {"status": "missing_csv"})
        if self.csv_file and not Path(self.csv_file).expanduser().is_file() and self.source == "csv":
            return _error(f"CSV de origem Pushtunes não encontrado: {self.csv_file}", {"status": "missing_csv"})
        if self.ytm_auth_file and not Path(self.ytm_auth_file).expanduser().is_file():
            return _error(f"Ficheiro browser.json do YouTube Music não encontrado: {self.ytm_auth_file}", {"status": "missing_ytm_auth"})
        if self.target == "tidal" and not self.tidal_session_file:
            return _error("Indique o ficheiro tidal-session.json para usar o destino Tidal.", {"status": "missing_tidal_session"})
        if self.tidal_session_file and not Path(self.tidal_session_file).expanduser().is_file():
            return _error(f"Ficheiro de sessão Tidal não encontrado: {self.tidal_session_file}", {"status": "missing_tidal_session"})
        if self.target == "csv" and not self.csv_file:
            return _error("Indique um CSV de destino quando o alvo Pushtunes for csv.", {"status": "missing_csv"})
        if self.operation == "playlist" and not self.playlist_name and not self.profile:
            return _error("Indique o nome da playlist ou use um perfil Pushtunes.", {"status": "missing_playlist_name"})
        if self.working_directory and not Path(self.working_directory).expanduser().is_dir():
            return _error(f"Directório de trabalho Pushtunes não encontrado: {self.working_directory}", {"status": "missing_working_directory"})
        return IntegrationResult(True, "Pushtunes pronto para sincronização de biblioteca.", {"command": prefix, "source": self.source, "target": self.target, "operation": self.operation})

    def _args(self) -> list[str]:
        args = ["push", self.operation, "--from", self.source, "--to", self.target, "--no-color"]
        try:
            args.extend(["--similarity", str(max(0.0, min(1.0, float(self.similarity))))])
        except (TypeError, ValueError):
            args.extend(["--similarity", "0.8"])
        if self.profile:
            args.extend(["--profile", str(Path(self.profile).expanduser().resolve())])
        if self.csv_file:
            args.extend(["--csv-file", str(Path(self.csv_file).expanduser().resolve())])
        if self.ytm_auth_file and self.operation in {"albums", "playlist"}:
            args.extend(["--ytm-auth", str(Path(self.ytm_auth_file).expanduser().resolve())])
        if self.operation == "playlist" and self.playlist_name:
            args.extend(["--playlist-name", self.playlist_name])
        return args

    def sync(self) -> IntegrationResult:
        status = self.status()
        if not status.ok:
            return status
        prefix = self._command_prefix() or []
        env = os.environ.copy()
        if self.spotify_client_id:
            env["SPOTIFY_CLIENT_ID"] = self.spotify_client_id
        if self.spotify_client_secret:
            env["SPOTIFY_CLIENT_SECRET"] = self.spotify_client_secret
        if self.spotify_redirect_uri:
            env["SPOTIFY_REDIRECT_URI"] = self.spotify_redirect_uri
        command = [*prefix, *self._args()]
        secrets = [self.spotify_client_id, self.spotify_client_secret]
        temporary_cwd: tempfile.TemporaryDirectory[str] | None = None
        execution_cwd = str(Path(self.working_directory).expanduser().resolve()) if self.working_directory else None
        if (self.ytm_auth_file and self.operation == "tracks") or self.tidal_session_file:
            temporary_cwd = tempfile.TemporaryDirectory(prefix="thunderbolt-pushtunes-")
            if self.ytm_auth_file and self.operation == "tracks":
                shutil.copy2(Path(self.ytm_auth_file).expanduser(), Path(temporary_cwd.name) / "browser.json")
            if self.tidal_session_file:
                shutil.copy2(Path(self.tidal_session_file).expanduser(), Path(temporary_cwd.name) / "tidal-session.json")
            execution_cwd = temporary_cwd.name
        try:
            completed = subprocess.run(
                command,
                cwd=execution_cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return _error(f"Não foi possível iniciar o Pushtunes: {exc}", {"status": "process_error"})
        finally:
            if temporary_cwd is not None:
                temporary_cwd.cleanup()
        stdout = _redact_output(completed.stdout, secrets)
        stderr = _redact_output(completed.stderr, secrets)
        data = {"command": command, "returncode": completed.returncode, "stdout": stdout, "stderr": stderr, "source": self.source, "target": self.target, "operation": self.operation}
        if completed.returncode != 0:
            return _error("O Pushtunes terminou com erro. Consulte a saída técnica abaixo e confirme as credenciais do serviço de origem/destino.", data)
        return IntegrationResult(True, f"Pushtunes concluiu a sincronização {self.source} → {self.target}.", data)


__all__ = [
    "DEFAULT_JEWELMUSIC_BASE_URL",
    "JewelMusicAdapter",
    "MUSIC_UPLOAD_EXTENSIONS",
    "PUSHTUNES_OPERATIONS",
    "PUSHTUNES_SOURCES",
    "PUSHTUNES_TARGETS",
    "PushtunesAdapter",
    "YTMusicApiAdapter",
    "YT_MUSIC_UPLOAD_EXTENSIONS",
]
