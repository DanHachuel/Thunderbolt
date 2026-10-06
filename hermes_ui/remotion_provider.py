"""Remotion como provedor de vídeo local do Thunderbolt.

O pipeline (`hermes_ui/pipeline_worker.py`) invoca o wrapper
`packages/remotion/render.mjs` como subprocesso Node.js — exactamente o
padrão já usado pelo MoneyPrinterTurbo/MPT via `uv`, com heartbeat,
timeout, cancelamento e `_stop_process` (psutil, nunca `taskkill /T /F`).

Responsabilidades (especificação "Integração do Remotion como Provedor de
Vídeo no Thunderbolt"):
- get_remotion_status(): verifica Node.js >= 18, FFmpeg (imageio-ffmpeg),
  Chromium (Playwright), @remotion/renderer instalado e bundle preparável.
- prepare_input_props(): converte o roteiro Markdown em inputProps JSON
  (o adaptador scriptToInputProps corre dentro do Node via --prepare-only).
- run_remotion_render(): executa o render com progresso, heartbeat, timeout
  de 15 minutos e cleanup robusto.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hermes_ui.storage import STORAGE

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTION_PACKAGE_DIR = REPO_ROOT / "packages" / "remotion"
REMOTION_RENDER_SCRIPT = REMOTION_PACKAGE_DIR / "render.mjs"
REMOTION_ENTRY_POINT = REMOTION_PACKAGE_DIR / "src" / "index.ts"
REMOTION_ROLE_MARKER = "--thunderbolt-role=remotion-render"
REMOTION_DEFAULT_TIMEOUT_SECONDS = 15 * 60
REMOTION_PREPARE_TIMEOUT_SECONDS = 60
REMOTION_HEARTBEAT_INTERVAL_SECONDS = 5

COMPOSITION_SIZES = {
    "LongFormVideo": (1920, 1080),
    "ShortVideo": (1080, 1920),
}


class RemotionProviderError(RuntimeError):
    """Falha accionável do provider Remotion (ambiente, conversão ou render)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────── Detecção de ambiente ────────────────────────────


def _find_node_executable() -> str | None:
    return shutil.which("node")


def _node_satisfiable_version(node: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    raw = str(result.stdout or result.stderr or "").strip()
    match = re.match(r"v?(\d+)\.", raw)
    if not match:
        return False, raw
    major = int(match.group(1))
    return major >= 18, raw


def _ffmpeg_executable() -> str | None:
    try:
        import imageio_ffmpeg

        candidate = str(imageio_ffmpeg.get_ffmpeg_exe() or "")
    except Exception:
        return None
    if candidate and Path(candidate).is_file():
        return candidate
    return None


def _playwright_browser_roots() -> list[Path]:
    """Pastas onde o Playwright/patchright guardam os browsers instalados."""
    roots: list[Path] = []
    env_root = str(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "")
    if env_root and env_root != "0" and Path(env_root).is_dir():
        roots.append(Path(env_root))
    if os.name == "nt":
        local_appdata = str(os.environ.get("LOCALAPPDATA") or "")
        if local_appdata:
            roots.append(Path(local_appdata) / "ms-playwright")
    else:
        roots.append(Path.home() / ".cache" / "ms-playwright")
    return roots


def _chromium_executable() -> str | None:
    """Caminho do Chromium do Playwright, lido directamente do disco.

    0.9.54: a versão anterior arrancava o driver do Playwright só para ler
    `executable_path`. Dentro do thread do Streamlit, um rerun interrompido
    podia destruir a conexão a meio do init e deixava no terminal
    "Task was destroyed but it is pending!" + TargetClosedError. O glob é
    instantâneo, não cria tarefas assíncronas e não lança nenhum processo.
    Cobre o Chromium do Playwright e do patchright (ambos instalam em
    ms-playwright).
    """
    def revision(directory: Path) -> int:
        match = re.search(r"(\d+)$", directory.name)
        return int(match.group(1)) if match else 0

    executable_layouts = (
        "chrome-win64/chrome.exe",
        "chrome-win/chrome.exe",
        "chrome-linux/chrome",
        "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    )
    shell_layouts = (
        "chrome-win64/headless_shell.exe",
        "chrome-win/headless_shell.exe",
        "chrome-linux/headless_shell",
    )
    for root in _playwright_browser_roots():
        try:
            chromium_dirs = sorted(
                [item for item in root.glob("chromium-*") if item.is_dir()],
                key=revision,
                reverse=True,
            )
        except OSError:
            continue
        for layout in executable_layouts:
            for browser_dir in chromium_dirs:
                candidate = browser_dir / layout
                if candidate.is_file():
                    return str(candidate)
        try:
            shell_dirs = sorted(
                [item for item in root.glob("chromium_headless_shell-*") if item.is_dir()],
                key=revision,
                reverse=True,
            )
        except OSError:
            continue
        for layout in shell_layouts:
            for browser_dir in shell_dirs:
                candidate = browser_dir / layout
                if candidate.is_file():
                    return str(candidate)
    return None


def _renderer_dependency_installed(node: str) -> bool:
    probe = (
        "import('@remotion/renderer').then(() => process.exit(0)).catch(() => process.exit(1))"
    )
    try:
        result = subprocess.run(
            [node, "-e", probe],
            cwd=str(REMOTION_PACKAGE_DIR),
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def get_remotion_status() -> dict[str, Any]:
    """Verifica Node.js, FFmpeg, Chromium, @remotion/renderer e o pacote.

    Devolve {"available": bool, "reasons": [...]} com razões accionáveis
    (a UI mostra-as e sugere como resolver cada uma).
    """
    reasons: list[str] = []
    details: dict[str, Any] = {}

    node = _find_node_executable()
    if not node:
        reasons.append("Node.js 18+ é necessário — instale em https://nodejs.org e reabra o Thunderbolt.")
    else:
        ok, version = _node_satisfiable_version(node)
        details["node"] = version
        if not ok:
            reasons.append(f"Node.js 18+ é necessário (detectado {version or 'versão desconhecida'}).")

    ffmpeg = _ffmpeg_executable()
    details["ffmpeg"] = ffmpeg or ""
    if not ffmpeg:
        reasons.append("O FFmpeg do imageio-ffmpeg não foi encontrado — reinstale as dependências Python do Thunderbolt.")

    chromium = _chromium_executable()
    details["chromium"] = chromium or ""
    if not chromium:
        reasons.append("O Chromium do Playwright não foi encontrado — corra a instalação do Thunderbolt para o instalar.")

    if not REMOTION_PACKAGE_DIR.is_dir() or not REMOTION_RENDER_SCRIPT.is_file() or not REMOTION_ENTRY_POINT.is_file():
        reasons.append("O pacote packages/remotion não está instalado nesta cópia do Thunderbolt.")
    elif node and not _renderer_dependency_installed(node):
        reasons.append(
            "As dependências do Remotion não estão instaladas — corra a instalação do Thunderbolt "
            "(npx.cmd --yes @danhachuel/thunderbolt@<versão> install) ou `npm install` dentro de packages/remotion/."
        )

    return {
        "available": not reasons,
        "reasons": reasons,
        "details": details,
    }


# ─────────────────── Roteiro Markdown → inputProps (Node) ────────────────────


def _script_markdown(script: dict[str, Any] | str) -> str:
    if isinstance(script, str):
        return script
    return str((script or {}).get("content") or "")


def _write_payload(directory: Path, stem: str, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def prepare_input_props(script: dict[str, Any] | str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Converte o roteiro (Markdown) em inputProps via scriptToInputProps (Node).

    O Python escreve o roteiro e a config; o wrapper corre com --prepare-only
    (sem render) e devolve o JSON no stdout.
    """
    node = _find_node_executable()
    if not node or not REMOTION_RENDER_SCRIPT.is_file():
        raise RemotionProviderError("O runtime Node.js ou o pacote packages/remotion não está disponível.")
    config = dict(config or {})
    directory = STORAGE / "remotion" / "input"
    stem = re.sub(r"[^\w-]", "-", str(config.get("videoId") or "script"))[:80] or "script"
    script_path = directory / f"{stem}.md"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_script_markdown(script), encoding="utf-8")
    config_path = _write_payload(directory, f"{stem}-config", config)
    command = [
        node,
        str(REMOTION_RENDER_SCRIPT),
        "--prepare-only",
        "--script-file",
        str(script_path),
        "--config",
        str(config_path),
        REMOTION_ROLE_MARKER,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(REMOTION_PACKAGE_DIR),
            capture_output=True,
            text=True,
            timeout=REMOTION_PREPARE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RemotionProviderError(f"Não foi possível executar o adaptador Remotion: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[-500:]
        raise RemotionProviderError(f"O adaptador Remotion falhou: {detail or 'sem detalhes'}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RemotionProviderError(f"O adaptador Remotion devolveu JSON inválido: {exc}") from exc


# ──────────────────────────── Render com heartbeat ───────────────────────────


def audio_duration_seconds(audio_path: Path) -> float | None:
    """Duração real do áudio TTS (recalcular as cenas quando o áudio existe)."""
    try:
        from moviepy import AudioFileClip

        with AudioFileClip(str(audio_path)) as clip:
            duration = clip.duration
        return float(duration) if duration and duration > 0 else None
    except Exception:
        return None


def _pipeline_hooks(
    stop_process: Callable[..., None] | None,
    update: Callable[..., Any] | None,
    heartbeat: Callable[..., None] | None,
    task_by_id: Callable[[str], dict[str, Any] | None] | None,
    persist_diagnostics: Callable[..., None] | None,
) -> dict[str, Callable[..., Any]]:
    """Resolve os hooks do pipeline_worker por injeção (testes) ou lazy import."""
    def _lazy(name: str) -> Callable[..., Any]:
        def resolve(*args, **kwargs):
            from hermes_ui import pipeline_worker

            return getattr(pipeline_worker, name)(*args, **kwargs)

        return resolve

    return {
        "stop_process": stop_process or _lazy("_stop_process"),
        "update": update or _lazy("_update"),
        "heartbeat": heartbeat or _lazy("_worker_heartbeat"),
        "task_by_id": task_by_id or _lazy("_task_by_id"),
        "persist_diagnostics": persist_diagnostics or _lazy("_persist_video_diagnostics"),
    }


def run_remotion_render(
    task: dict[str, Any],
    video_path: Path,
    composition_id: str,
    input_props: dict[str, Any],
    timeout_seconds: int = REMOTION_DEFAULT_TIMEOUT_SECONDS,
    *,
    stop_process: Callable[..., None] | None = None,
    update: Callable[..., Any] | None = None,
    heartbeat: Callable[..., None] | None = None,
    task_by_id: Callable[[str], dict[str, Any] | None] | None = None,
    persist_diagnostics: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Executa o subprocesso Remotion com heartbeat, timeout e cleanup.

    Padrão de _run_video_helper_once (MPT): Popen + threads leitoras, heartbeat
    de 5s com _update/_worker_heartbeat, cancelamento via estado da tarefa,
    timeout com _stop_process (psutil) e finally com reader.join() +
    _persist_video_diagnostics tolerante a falhas.
    """
    task_id = str(task.get("id") or "")
    node = _find_node_executable()
    if not node or not REMOTION_RENDER_SCRIPT.is_file():
        raise RemotionProviderError("O runtime Node.js ou o pacote packages/remotion não está disponível.")

    props_directory = STORAGE / "remotion" / "input"
    stem = re.sub(r"[^\w-]", "-", str(input_props.get("videoId") or task_id or "props"))[:80] or "props"
    props_path = _write_payload(props_directory, f"{stem}-final", input_props)
    cache_dir = STORAGE / "remotion-cache"
    status = get_remotion_status()
    if not status.get("available"):
        raise RemotionProviderError("Remotion indisponível: " + "; ".join(status.get("reasons") or ["ambiente incompleto"]))

    command = [
        node,
        str(REMOTION_RENDER_SCRIPT),
        "--input-props",
        str(props_path),
        "--output",
        str(video_path),
        "--composition",
        str(composition_id),
        "--cache-dir",
        str(cache_dir),
        REMOTION_ROLE_MARKER,
    ]
    chromium = str((status.get("details") or {}).get("chromium") or "")
    ffmpeg = str((status.get("details") or {}).get("ffmpeg") or "")
    if chromium:
        command.extend(["--chromium", chromium])
    if ffmpeg:
        command.extend(["--ffmpeg", ffmpeg])

    hooks = _pipeline_hooks(stop_process, update, heartbeat, task_by_id, persist_diagnostics)
    line_queue: queue.Queue[str | None] = queue.Queue(maxsize=500)
    output_lines: list[str] = []
    last_progress = 0.0

    def _enqueue(value: str | None) -> None:
        try:
            line_queue.put_nowait(value)
        except queue.Full:
            try:
                line_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                line_queue.put_nowait(value)
            except queue.Full:
                pass

    def _read_stream(stream) -> None:
        try:
            for raw in iter(stream.readline, ""):
                _enqueue(raw.rstrip())
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass
            _enqueue(None)

    try:
        process = subprocess.Popen(
            command,
            cwd=str(REMOTION_PACKAGE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=os.name != "nt",
        )
    except OSError as exc:
        raise RemotionProviderError(f"Não foi possível iniciar o subprocesso Remotion: {exc}") from exc

    readers = [
        threading.Thread(target=_read_stream, args=(process.stdout,), name=f"remotion-stdout-{task_id}", daemon=True),
        threading.Thread(target=_read_stream, args=(process.stderr,), name=f"remotion-stderr-{task_id}", daemon=True),
    ]
    for reader in readers:
        reader.start()
    stream_endings = 0
    started_at = time.monotonic()
    last_heartbeat = 0.0
    last_status_line = ""
    finished = False
    timed_out = False
    cancelled = False

    try:
        while True:
            try:
                line = line_queue.get(timeout=0.5)
                if line is None:
                    stream_endings += 1
                elif line:
                    last_status_line = line[-500:]
                    output_lines.append(line)
                    progress_match = re.match(r"PROGRESS=(\d+(?:\.\d+)?)", line)
                    if progress_match:
                        last_progress = float(progress_match.group(1))
            except queue.Empty:
                pass
            elapsed = time.monotonic() - started_at
            if elapsed - last_heartbeat >= REMOTION_HEARTBEAT_INTERVAL_SECONDS and not finished:
                # Banda reservada da etapa vídeo (52–79), sem fingir conclusão:
                # a percentagem real do Remotion mapeia para o interior da banda.
                video_progress = int(52 + min(1.0, max(0.0, last_progress / 100.0)) * 27)
                current_task = hooks["task_by_id"](task_id) if task_id else None
                if current_task and str(current_task.get("state") or "") in {"blocked", "cancelled"}:
                    cancelled = True
                    raise _CancelledByUser()
                hooks["update"](
                    task_id,
                    progress=video_progress,
                    video_helper_status=last_status_line,
                    video_elapsed_seconds=int(elapsed),
                )
                hooks["heartbeat"](
                    task_id=task_id,
                    status="running",
                    stage="video",
                    progress=video_progress,
                    video_helper_status=last_status_line,
                    video_elapsed_seconds=int(elapsed),
                )
                last_heartbeat = elapsed
            if stream_endings >= 2:
                finished = True
            if finished and process.poll() is not None:
                break
            if elapsed >= timeout_seconds:
                timed_out = True
                break
    except _CancelledByUser:
        cancelled = True
    finally:
        if process.poll() is None:
            hooks["stop_process"](process, reason="cancelled" if cancelled else ("timeout" if timed_out else "cleanup"))
        for reader in readers:
            try:
                reader.join(timeout=2)
            except Exception:
                pass
        try:
            hooks["persist_diagnostics"](task, "\n".join(output_lines[-200:]))
        except Exception:
            pass

    if timed_out:
        raise RemotionProviderError(
            f"A etapa Vídeo (Remotion) excedeu o limite de {timeout_seconds // 60} minutos e foi encerrada."
        )
    if cancelled:
        from hermes_ui.pipeline_worker import PipelineStopped

        raise PipelineStopped("A tarefa foi parada pelo utilizador.")
    if process.returncode != 0:
        detail = "\n".join(output_lines[-30:])[-500:]
        raise RemotionProviderError(f"O render Remotion falhou: {detail or 'sem detalhe devolvido pelo wrapper'}")

    output_match = re.search(r"(?m)^OUTPUT=(.+)$", "\n".join(output_lines))
    rendered = Path(output_match.group(1).strip()) if output_match else video_path
    if not rendered.is_file() or rendered.stat().st_size <= 0:
        raise RemotionProviderError("O render Remotion terminou sem devolver um MP4 válido.")
    return {
        "video_path": str(rendered),
        "output": str(rendered),
        "composition": composition_id,
        "finished_at": _now(),
        "elapsed_seconds": int(time.monotonic() - started_at),
    }


class _CancelledByUser(Exception):
    """Sinal interno: a tarefa foi parada pelo utilizador durante o render."""
