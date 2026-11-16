"""Verificação e actualização local da versão distribuída pelo NPM.

O módulo não recebe nem manipula credenciais. A instalação só é iniciada após o
clique explícito do utilizador na interface local.

1.1.02 — a actualização passou a correr em SEGUNDO PLANO. O caminho antigo
(`update_to_latest`, síncrono) bloqueava a thread do Streamlit dentro do
`st.spinner` durante os 5-20 minutos do `npx install`: o browser ficava em
"Connecting..." e o utilizador não tinha nenhuma prova de progresso. Agora
`start_update()` lança o instalador com `asyncio.create_subprocess_exec` numa
thread daemon, escreve tudo em `storage/logs/update.log` e publica o estado em
`storage/state/update_status.json` — a UI faz polling a esse ficheiro num
`st.fragment`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from . import storage
from .automation_worker import _pid_alive


PACKAGE_NAME = "@danhachuel/thunderbolt"
REGISTRY_URL = "https://registry.npmjs.org/@danhachuel/thunderbolt/latest"
UPDATE_TIMEOUT_SECONDS = 20 * 60
LAUNCHER_RESTART_EXIT_CODE = 75
UPDATE_LOG_NAME = "update.log"
UPDATE_STATUS_NAME = "update_status.json"
UPDATE_LOG_MAX_BYTES = 5 * 1024 * 1024
IDLE_STATUS: dict[str, Any] = {"status": "idle"}

_start_lock = threading.Lock()


@dataclass(frozen=True)
class VersionCheck:
    """Version information displayed on the local home page."""

    current_version: str
    latest_version: str = ""
    error: str = ""

    @property
    def update_available(self) -> bool:
        latest_key = _version_key(self.latest_version)
        current_key = _version_key(self.current_version)
        if latest_key is not None and current_key is not None:
            return latest_key > current_key
        return bool(self.latest_version and self.current_version and self.latest_version != self.current_version)


def _version_key(value: str) -> tuple[int, int, int] | None:
    """Return a numeric SemVer core so zero-padded patches compare correctly."""
    raw = str(value or "").strip().lstrip("v")
    core = raw.split("+", 1)[0].split("-", 1)[0]
    parts = core.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


@dataclass(frozen=True)
class UpdateResult:
    """Sanitised result of an explicit local package update request."""

    ok: bool
    latest_version: str = ""
    message: str = ""
    restart_required: bool = False
    status: str = ""  # idle | running | done | error (estado do job em background)


def restart_current_process(*, exec_fn: Callable[..., Any] = os.execv, exit_fn: Callable[[int], Any] = os._exit) -> None:
    """Ask the launcher to restart Streamlit, or re-exec standalone callers."""
    if os.environ.get("THUNDERBOLT_LAUNCHER_RESTART") == "1":
        exit_fn(LAUNCHER_RESTART_EXIT_CODE)
        return
    executable = sys.executable
    exec_fn(executable, [executable, *sys.argv])


def latest_package_version(*, timeout: int = 8, get: Callable[..., Any] = requests.get) -> str:
    """Return the latest public package version without sending local configuration."""
    response = get(REGISTRY_URL, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    version = str(payload.get("version") or "").strip() if isinstance(payload, dict) else ""
    if not version:
        raise ValueError("O registry NPM não devolveu uma versão válida.")
    return version


def check_version(current_version: str, *, timeout: int = 8, get: Callable[..., Any] = requests.get) -> VersionCheck:
    """Fetch only the package metadata needed for the version badge."""
    current = str(current_version or "").strip()
    try:
        return VersionCheck(current_version=current, latest_version=latest_package_version(timeout=timeout, get=get))
    except (requests.RequestException, ValueError) as exc:
        return VersionCheck(current_version=current, error=f"Não foi possível verificar actualizações agora ({type(exc).__name__}).")


def update_command() -> list[str]:
    """Build the same cross-platform install command documented for Thunderbolt."""
    executable = "npx.cmd" if os.name == "nt" else "npx"
    return [executable, "--yes", "--prefer-online", PACKAGE_NAME, "install"]


# ---------------------------------------------------------------------------
# 1.1.02 - actualizacao em segundo plano (log + ficheiro de estado)
# ---------------------------------------------------------------------------


def update_log_path() -> Path:
    """Onde o instalador escreve (a mesma pasta dos restantes logs do app)."""
    return storage.STORAGE / "logs" / UPDATE_LOG_NAME


def read_update_status() -> dict[str, Any]:
    """Estado do job de actualizacao, lido pela UI num `st.fragment`.

    1.1.02 - um job corre numa thread DAEMON: se o processo morrer a meio
    (encerramento do utilizador, crash, update do launcher), o ficheiro ficaria
    "running" para sempre e a UI mostraria o spinner sem nada a acontecer. O
    estado guarda o PID de quem o lancou; se esse processo ja nao existe, o
    estado e corrigido para "error" com a mensagem de interrupcao.
    """
    current = storage.read_json(UPDATE_STATUS_NAME, None)
    if not isinstance(current, dict):
        return dict(IDLE_STATUS)
    state = dict(current)
    if state.get("status") != "running":
        return state
    pid = int(state.get("pid") or 0)
    if pid and pid == os.getpid():
        return state  # o job e deste processo: a thread daemon ainda corre
    # marcador sem separador: o cmdline do Windows usa `app\main.py` e o do
    # POSIX `app/main.py` - "main.py" casa com os dois.
    if pid and _pid_alive(pid, expect_marker="main.py"):
        return state  # outro processo vivo ainda esta a instalar
    estado = {
        **state,
        "status": "error",
        "message": "A actualizacao foi interrompida (o processo terminou). Veja storage/logs/update.log.",
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_update_status(estado)
    return estado


def _write_update_status(payload: dict[str, Any]) -> None:
    """Escrita ATOMICA (storage.write_json) - a UI le a cada poucos segundos."""
    try:
        storage.write_json(UPDATE_STATUS_NAME, {**IDLE_STATUS, **payload})
    except Exception:  # noqa: BLE001 - o estado nunca pode derrubar a actualizacao
        pass


def _tail(path: Path, lines: int = 40) -> str:
    """Ultimas linhas do log - o que a UI mostra quando algo corre mal."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(content.strip().splitlines()[-lines:])


def _log_header(log_handle: Any, command: list[str], latest_version: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_handle.write(
        f"\n--- {stamp} actualizacao para {latest_version} iniciada pela interface ---\n"
        f"$ {' '.join(command)}\n"
    )
    log_handle.flush()


def _open_log(command: list[str], latest_version: str) -> Any:
    log_path = update_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size > UPDATE_LOG_MAX_BYTES:
        log_path.write_text("", encoding="utf-8")  # rotacao simples: 5 MB
    handle = log_path.open("a", encoding="utf-8")
    _log_header(handle, command, latest_version)
    return handle


async def _run_update_async(
    current_version: str,
    latest_version: str,
    *,
    timeout: int = UPDATE_TIMEOUT_SECONDS,
    create_subprocess_exec: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Corre o instalador em background e publica o estado a cada transicao."""
    command = update_command()
    factory = create_subprocess_exec or asyncio.create_subprocess_exec
    _write_update_status(
        {
            "status": "running",
            "current_version": current_version,
            "latest_version": latest_version,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "command": " ".join(command),
            "pid": os.getpid(),
        }
    )
    log_handle = _open_log(command, latest_version)
    try:
        try:
            process = await factory(
                *command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            log_handle.write(f"nao foi possivel iniciar o instalador: {exc}\n")
            payload = {
                "status": "error",
                "latest_version": latest_version,
                "message": f"Nao foi possivel iniciar a actualizacao ({type(exc).__name__}).",
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            _write_update_status(payload)
            return payload
        try:
            returncode = await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            log_handle.write(f"\nTEMPO LIMITE ({timeout}s) excedido; instalador terminado.\n")
            payload = {
                "status": "error",
                "latest_version": latest_version,
                "message": "A actualizacao excedeu o tempo limite. Veja storage/logs/update.log.",
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            _write_update_status(payload)
            return payload
        if int(returncode or 0) != 0:
            payload = {
                "status": "error",
                "latest_version": latest_version,
                "message": "A actualizacao nao foi concluida. Veja storage/logs/update.log.",
                "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_code": int(returncode or 0),
            }
            _write_update_status(payload)
            return payload
        payload = {
            "status": "done",
            "latest_version": latest_version,
            "message": (
                f"A versao {latest_version} foi instalada. "
                "Reinicie o Thunderbolt para abrir a versao nova."
            ),
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "restart_required": True,
        }
        _write_update_status(payload)
        return payload
    finally:
        try:
            log_handle.close()
        except OSError:
            pass


def _run_update_in_thread(current_version: str, latest_version: str, timeout: int) -> None:
    """Thread daemon: a UI nunca bloqueia e o job sobrevive a um rerun."""

    def _target() -> None:
        try:
            asyncio.run(_run_update_async(current_version, latest_version, timeout=timeout))
        except Exception as exc:  # noqa: BLE001 - o estado tem de reflectir a falha
            _write_update_status(
                {
                    "status": "error",
                    "latest_version": latest_version,
                    "message": f"Falha inesperada na actualizacao ({type(exc).__name__}).",
                    "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

    threading.Thread(target=_target, name="thunderbolt-update", daemon=True).start()


def _announce_update(command: list[str]) -> None:
    """Uma linha no terminal com o comando que esta a correr (nunca o output)."""
    try:
        print(
            "[SISTEMA] A actualizar o Thunderbolt: "
            f"{' '.join(command)} (log: {update_log_path()})",
            file=sys.stderr,
        )
    except (ValueError, OSError):
        pass  # stderr fechado num rerun: o anuncio e opcional


def start_update(
    current_version: str,
    *,
    timeout: int = UPDATE_TIMEOUT_SECONDS,
    get: Callable[..., Any] = requests.get,
) -> UpdateResult:
    """Lanca a actualizacao em background e devolve o estado IMEDIATAMENTE.

    Nao bloqueia a thread do Streamlit: quem quiser acompanhar le
    `read_update_status()` (a UI faz isso num `st.fragment` a cada 2 s).
    """
    status = check_version(current_version, get=get)
    if status.error:
        return UpdateResult(False, message=status.error, status="error")
    if not status.update_available:
        return UpdateResult(
            True,
            latest_version=status.latest_version,
            message="O Thunderbolt ja esta na versao mais recente.",
            status="idle",
        )
    with _start_lock:
        current_status = read_update_status()
        if current_status.get("status") == "running":
            return UpdateResult(
                True,
                latest_version=status.latest_version,
                message="Uma actualizacao ja esta a correr. A companhar em storage/logs/update.log.",
                status="running",
            )
        # Publica "running" JA (antes da thread arrancar): assim um segundo
        # clique, mesmo uns milissegundos depois, ve o job em curso e nao lanca
        # um segundo instalador a disputar o .runtime.
        _write_update_status(
            {
                "status": "running",
                "current_version": current_version,
                "latest_version": status.latest_version,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "command": " ".join(update_command()),
                "pid": os.getpid(),
            }
        )
        _run_update_in_thread(current_version, status.latest_version, timeout)
    _announce_update(update_command())
    return UpdateResult(
        True,
        latest_version=status.latest_version,
        message=f"A instalar a versao {status.latest_version}...",
        status="running",
    )


def update_to_latest(
    current_version: str,
    *,
    timeout: int = UPDATE_TIMEOUT_SECONDS,
    get: Callable[..., Any] = requests.get,
    run: Callable[..., Any] | None = None,
) -> UpdateResult:
    """Install the latest package only after an explicit UI action.

    The running local process keeps its current code until it is restarted. No
    subprocess output is returned to the UI, preventing accidental display of
    environment values from third-party installers.

    1.1.02 - a UI passou a usar `start_update()` (background + log). Este
    caminho sincrono fica como FALLBACK: corre o mesmo instalador e escreve a
    mesma saida em `storage/logs/update.log`, para o utilizador poder Diagnostic
    uma falha. Nenhum output de instalador volta para a UI.
    """
    status = check_version(current_version, get=get)
    if status.error:
        return UpdateResult(False, message=status.error)
    if not status.update_available:
        return UpdateResult(True, latest_version=status.latest_version, message="O Thunderbolt já está na versão mais recente.")
    command = update_command()
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "timeout": timeout,
        "check": False,
    }
    if run is None:
        # fallback real: instalador com a saida no log, nunca no terminal
        log_handle = _open_log(command, status.latest_version)
        try:
            completed = subprocess.run(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                **kwargs,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log_handle.write(f"\n{type(exc).__name__}: {exc}\n")
            return UpdateResult(False, latest_version=status.latest_version, message=f"Não foi possível concluir a actualização ({type(exc).__name__}).")
        finally:
            try:
                log_handle.close()
            except OSError:
                pass
    else:
        completed = run(command, **kwargs)
    if int(getattr(completed, "returncode", 1)) != 0:
        return UpdateResult(False, latest_version=status.latest_version, message="A actualização não foi concluída. Feche processos Thunderbolt em execução e tente novamente.")
    return UpdateResult(
        True,
        latest_version=status.latest_version,
        restart_required=True,
        message=(
            f"A versão {status.latest_version} foi instalada. Reinicie o Thunderbolt para abrir a versão nova; "
            "os dados e configurações locais foram preservados."
        ),
    )
    return UpdateResult(
        True,
        latest_version=status.latest_version,
        restart_required=True,
        message=(
            f"A versão {status.latest_version} foi instalada. Reinicie o Thunderbolt para abrir a versão nova; "
            "os dados e configurações locais foram preservados."
        ),
    )
