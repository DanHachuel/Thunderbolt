"""1.0.51 — Patch de RUNTIME do motor MoneyPrinterTurbo (fim do WinError 32).

O motor (clone oficial ``harry0703/MoneyPrinterTurbo`` instalado fora deste
repo) escreve o áudio temporário do MoviePy com um nome ESTÁTICO derivado do
ficheiro de saída — ``final-1.mp4`` → ``final-1TEMP_MPY_wvf_snd.mp4``
(moviepy: ``name + Clip._TEMP_FILES_PREFIX + "wvf_snd." + find_extension``).
Todos os renders e todos os processos concorrentes partilham o MESMO caminho
no TEMP isolado (``%LOCALAPPDATA%\\THUNDERBOLT\\temp`` desde a 1.0.43): com o
«Refazer Vídeo» (ou dois renders em paralelo) a escrita/limpeza colide e o
Windows devolve ``[WinError 32] O arquivo já está sendo usado por outro
processo``. O motor trata QUALQUER excepção do write como falha do codec:
desliga o encoder de hardware para todo o runtime e o render cai para a
codificação em CPU (prova nos logs reais do motor — a razão registada é o
próprio «[WinError 32] … final-1TEMP_MPY_wvf_snd.mp4»). A GPU está sana — é
bloqueio de ficheiro.

Como esse código vive no motor (fora deste repo), este módulo é injectado no
PROCESSO do motor pelo bootstrap do ``mpt_agent.py`` (``python -c "<importa e
aplica; runpy cli.py>"``) e aplica três camadas, todas defensivas (uma falha
de patch NUNCA impede o arranque do motor):

1. ``patch_moviepy_write_videofile`` — injecta um ``temp_audiofile`` com nome
   ÚNICO por execução (``final-1TEMP_MPY_<uuid4>_wvf_snd.mp4``), toma conta da
   limpeza com retry (``remove_temp=False`` quando suportado) e repete a
   escrita até 3x em WinError 32 com um nome fresco a cada tentativa;
2. ``patch_mpt_video_service`` — ``_disable_runtime_video_codec`` NUNCA
   desativa um codec por bloqueio de ficheiro (só por falha REAL de encoder);
   ``_write_videofile_with_codec_fallback`` repete o MESMO codec uma vez em
   WinError 32 e relança a falha sem tocar na GPU (nada de fallback
   falso-positivo para a codificação em CPU);
3. ``patch_mpt_video_service`` também força ``_get_temp_audio_dir`` no TEMP
   isolado do Thunderbolt, e a limpeza preventiva apaga ``*TEMP_MPY_*``
   órfãos com mais de 24 h antes do render.

Restrição honrada: o encoder de hardware CONTINUA activo — uma falha real de
GPU mantém o fallback e o aviso originais do motor (e o fail-fast do
Thunderbolt). Este módulo nunca menciona codec nenhum: só distingue bloqueio
de ficheiro de falha de encoder.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

# WinError 32 = ERROR_SHARING_VIOLATION («o arquivo já está sendo usado»).
WINDOWS_LOCK_ERROR = 32
# Pistas de mensagem: str(PermissionError) do Windows em PT/EN + a razão que o
# motor grava («reason: [WinError 32] …»). Só o Windows produz estes textos.
LOCK_MESSAGE_HINTS = (
    "winerror 32",
    "being used by another process",
    "sendo usado por outro processo",
    "esta siendo usado por outro processo",
    "already being used by another process",
)
# Nome do temporário do MoviePy: <stem do output> + TEMP_MPY_<uuid>_wvf_snd.
MPT_TEMP_AUDIO_PREFIX = "TEMP_MPY_"
MPT_TEMP_AUDIO_SUFFIX = "_wvf_snd"
MPT_TEMP_AUDIO_GLOB = "*TEMP_MPY_*"
ENGINE_TEMP_DIRNAME = "THUNDERBOLT"
# Limpeza preventiva: temporários órfãos com mais de 24 h.
ORPHAN_MAX_AGE_HOURS = 24
# Retry da escrita em bloqueio: 3 tentativas, backoff 0,5/1 s.
TEMP_AUDIO_ATTEMPTS = 3
TEMP_AUDIO_BACKOFF_SECONDS = 0.5
# Marcas nos objectos patchados (idempotência de apply()).
MOVIEPY_PATCH_MARKER = "_thunderbolt_unique_temp_audiofile"
LOCK_GUARD_MARKER = "_thunderbolt_lock_guard"
WRITER_RETRY_MARKER = "_thunderbolt_writer_lock_retry"
TEMP_DIR_GUARD_MARKER = "_thunderbolt_temp_dir_guard"

_APPLIED = False
_APPLY_RESULTS: dict[str, bool] = {}


def is_windows_lock_error(error: Any) -> bool:
    """Verdadeiro só para bloqueio de ficheiro do Windows (WinError 32).

    ``winerror`` é atributo exclusivo do Windows; em POSIX o errno 32 é EPIPE
    («broken pipe») e NUNCA deve ser confundido com lock. As pistas de
    mensagem cobrem a razão em texto que o motor passa a
    ``_disable_runtime_video_codec`` (PT-BR e EN).
    """
    if error is None:
        return False
    if getattr(error, "winerror", None) == WINDOWS_LOCK_ERROR:
        return True
    text = str(error).casefold()
    return any(hint in text for hint in LOCK_MESSAGE_HINTS)


def thunderbolt_engine_temp_dir() -> Path:
    """TEMP isolado e estável do Thunderbolt (espelho de hermes_ui.storage).

    Windows: ``%LOCALAPPDATA%\\THUNDERBOLT\\temp``; POSIX:
    ``$HOME/.thunderbolt/temp`` com o temp do sistema como último recurso —
    nunca um caminho Windows fora do Windows (o FFmpeg leria «C:» como
    protocolo). Este módulo corre no venv do motor: não pode importar o
    repo, daí a cópia fiel da política da 1.0.43.
    """
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or "C:\\")
        temp_dir = base / ENGINE_TEMP_DIRNAME / "temp"
    else:
        base = Path(os.getenv("HOME") or tempfile.gettempdir())
        temp_dir = base / ".thunderbolt" / "temp"
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(tempfile.gettempdir())
    return temp_dir


def unique_temp_audiofile_path(
    output_file: Any,
    temp_audiofile_path: Any = "",
    audio_ext: str = "mp4",
) -> Path:
    """Nome ÚNICO por execução para o áudio temporário do MoviePy.

    ``final-1.mp4`` → ``…/final-1TEMP_MPY_<uuid4-hex>_wvf_snd.mp4``: dois
    «Refazer Vídeo» (ou dois renders em paralelo) nunca partilham caminho —
    a colisão de nomes deixa de existir na origem. Directório vazio = TEMP
    isolado do Thunderbolt (nunca o CWD do motor).
    """
    output = Path(str(output_file))
    stem = output.stem or "clip"
    extension = str(audio_ext or "mp4").lstrip(".")
    token = uuid.uuid4().hex
    directory = (
        Path(str(temp_audiofile_path))
        if str(temp_audiofile_path or "").strip()
        else thunderbolt_engine_temp_dir()
    )
    return directory / f"{stem}{MPT_TEMP_AUDIO_PREFIX}{token}{MPT_TEMP_AUDIO_SUFFIX}.{extension}"


def _safe_unlink(path: Any, max_retries: int = TEMP_AUDIO_ATTEMPTS) -> bool:
    """Apaga com retry em WinError 32 (best-effitt: nunca rebenta)."""
    target = Path(str(path))
    for attempt in range(max_retries):
        try:
            target.unlink(missing_ok=True)
            return True
        except OSError as exc:
            if not is_windows_lock_error(exc) or attempt >= max_retries - 1:
                return False
            time.sleep(TEMP_AUDIO_BACKOFF_SECONDS * (2**attempt))
    return False


def cleanup_orphan_mpt_temp_files(
    max_age_hours: float = ORPHAN_MAX_AGE_HOURS,
    temp_dir: Any = "",
) -> int:
    """Apaga ``*TEMP_MPY_*`` órfãos com idade superior a ``max_age_hours``.

    Corre antes de cada render (mpt_agent) e no arranque do motor (bootstrap):
    um temporário esquecido de um render morto não pode bloquear o próximo.
    Devolve o número de ficheiros removidos.
    """
    directory = Path(str(temp_dir)) if str(temp_dir or "").strip() else thunderbolt_engine_temp_dir()
    if not directory.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    try:
        candidates = list(directory.glob(MPT_TEMP_AUDIO_GLOB))
    except OSError:
        return 0
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            if candidate.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        if _safe_unlink(candidate):
            removed += 1
    return removed


def _audio_extension(audio_codec: Any) -> str:
    """Extensão do contentor do áudio (mp4 para aac — como o próprio MoviePy)."""
    codec = str(audio_codec or "").strip()
    if not codec:
        return "mp4"
    try:
        from moviepy.tools import find_extension

        return find_extension(codec) or "mp4"
    except Exception:
        return "mp4"


def _supports_remove_temp(original: Callable[..., Any]) -> bool:
    """O ``write_videofile`` desta versão do MoviePy tem ``remove_temp``?"""
    try:
        import inspect

        return "remove_temp" in inspect.signature(original).parameters
    except Exception:
        return False


def patch_moviepy_write_videofile() -> bool:
    """Camada 1: escrita do MoviePy com temp único + retry em bloqueio.

    Envolve ``moviepy.video.VideoClip.VideoClip.write_videofile`` (ponto por
    onde passam TODAS as escritas do motor — clipes e vídeo final):
    - injeta ``temp_audiofile`` único quando o motor não opassou (o motor
      só passa ``temp_audiofile_path`` — o nome estático é do MoviePy);
    - passa ``remove_temp=False`` (quando suportado) e limpa o temporário
      com retry — a limpeza do MoviePy é um ``os.remove`` sem retry que
      rebenta com WinError 32 DEPOIS do vídeo estar pronto;
    - em WinError 32 repete até 3x com um nome fresco (o bloqueio pode ser
      transitório: Defender a varrer, handle do FFmpeg a fechar);
    - qualquer outro erro propaga de imediato (falha real de GPU/ffmpeg
      continua a cair no fallback legítimo do motor).
    """
    try:
        from moviepy.video.VideoClip import VideoClip
    except Exception:
        return False
    if getattr(VideoClip.write_videofile, MOVIEPY_PATCH_MARKER, False):
        return False
    original = VideoClip.write_videofile
    owns_remove_temp = _supports_remove_temp(original)

    def write_videofile_with_unique_temp(self, filename, *args, **kwargs):
        managed = not kwargs.get("temp_audiofile")
        temp_path: Path | None = None
        for attempt in range(TEMP_AUDIO_ATTEMPTS):
            call_kwargs = dict(kwargs)
            if managed:
                temp_path = unique_temp_audiofile_path(
                    filename,
                    call_kwargs.get("temp_audiofile_path") or "",
                    _audio_extension(call_kwargs.get("audio_codec")),
                )
                call_kwargs["temp_audiofile"] = str(temp_path)
                if owns_remove_temp:
                    call_kwargs["remove_temp"] = False
            try:
                result = original(self, filename, *args, **call_kwargs)
            except Exception as exc:
                if temp_path is not None:
                    _safe_unlink(temp_path)
                    temp_path = None
                if is_windows_lock_error(exc) and attempt + 1 < TEMP_AUDIO_ATTEMPTS:
                    time.sleep(TEMP_AUDIO_BACKOFF_SECONDS * (2**attempt))
                    continue
                raise
            if temp_path is not None:
                _safe_unlink(temp_path)
            return result
        return None  # inalcançável: o ciclo propaga na última tentativa

    setattr(write_videofile_with_unique_temp, MOVIEPY_PATCH_MARKER, True)
    VideoClip.write_videofile = write_videofile_with_unique_temp
    return True


def patch_mpt_video_service(module: Any = None) -> bool:
    """Camada 2+3: o motor deixa de confundir bloqueio de ficheiro com GPU.

    ``_disable_runtime_video_codec(codec, reason)`` torna-se um no-op quando a
    razão é WinError 32 — sessões do encoder esgotadas e drivers continuam a
    desligar o codec como antes. ``_write_videofile_with_codec_fallback``
    repete o MESMO codec uma vez em bloqueio (nome fresco pela camada 1) e
    relança a falha sem anúncio de queda para CPU: um lock persistente falha a
    tarefa com mensagem honesta em vez de sujar a telemetria e entregar CPU.
    ``_get_temp_audio_dir`` passa a devolver SEMPRE o TEMP isolado.
    """
    if module is None:
        try:
            from app.services import video as module
        except Exception:
            return False
    patched = False

    original_disable = getattr(module, "_disable_runtime_video_codec", None)
    if original_disable is not None and not getattr(original_disable, LOCK_GUARD_MARKER, False):
        def guarded_disable(codec: str, reason: str = "") -> Any:
            if is_windows_lock_error(reason):
                return None
            return original_disable(codec, reason)

        setattr(guarded_disable, LOCK_GUARD_MARKER, True)
        module._disable_runtime_video_codec = guarded_disable
        patched = True

    original_writer = getattr(module, "_write_videofile_with_codec_fallback", None)
    if original_writer is not None and not getattr(original_writer, WRITER_RETRY_MARKER, False):
        def writer_with_lock_retry(clip, output_file, codec, **kwargs):
            for attempt in range(2):
                try:
                    return original_writer(clip, output_file, codec, **kwargs)
                except Exception as exc:
                    if is_windows_lock_error(exc) and attempt == 0:
                        continue  # nome fresco (camada 1); lock não é falha de GPU
                    raise

        setattr(writer_with_lock_retry, WRITER_RETRY_MARKER, True)
        module._write_videofile_with_codec_fallback = writer_with_lock_retry
        patched = True

    original_temp_dir = getattr(module, "_get_temp_audio_dir", None)
    if original_temp_dir is not None and not getattr(
        original_temp_dir, TEMP_DIR_GUARD_MARKER, False
    ):
        def isolated_temp_audio_dir(output_dir: str = "") -> str:
            return str(thunderbolt_engine_temp_dir())

        setattr(isolated_temp_audio_dir, TEMP_DIR_GUARD_MARKER, True)
        module._get_temp_audio_dir = isolated_temp_audio_dir
        patched = True

    return patched


def _install_post_import_hook(target: str = "app.services.video") -> None:
    """Aplica o patch do motor no momento em que ``app.services.video`` entra.

    O ``cli.py`` importa o serviço DENTRO de ``run_cli`` (depois do parse e
    da preparação de ficheiros) — importar antes seria reordenar side
    effects. O hook de meta_path só interceptA ESSA importação e corre o
    patch logo a seguir ao loader original: zero risco de arranque, patch
    garantido muito antes da primeira escrita. ``target`` é parametrizável
    para o contrato de CI o exercitar sem importar o motor real.
    """
    import importlib.abc

    target = str(target or "")

    class _PatchAfterImport(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target_module=None):
            if fullname != target:
                return None
            remaining = [finder for finder in sys.meta_path if finder is not self]
            for finder in remaining:
                try:
                    spec = finder.find_spec(fullname, path, target_module)
                except Exception:
                    spec = None
                if spec is None or spec.loader is None:
                    continue
                original_exec = spec.loader.exec_module

                def exec_module(module, _original_exec=original_exec):
                    _original_exec(module)
                    try:
                        patch_mpt_video_service(module)
                        patch_moviepy_write_videofile()
                    except Exception:
                        pass

                spec.loader.exec_module = exec_module
                try:
                    sys.meta_path.remove(self)
                except ValueError:
                    pass
                return spec
            return None

    sys.meta_path.insert(0, _PatchAfterImport())


def apply(cleanup_orphans: bool = True) -> dict[str, bool]:
    """Aplica todas as camadas (idempotente). Nunca lança excepção.

    Corre no processo do motor via bootstrap do mpt_agent. Uma falha de uma
    camada NUNCA impede o arranque — o motor segue a funcionar como antes.
    """
    global _APPLIED
    if _APPLIED:
        return dict(_APPLY_RESULTS)
    results: dict[str, bool] = {}
    if cleanup_orphans:
        try:
            results["orphan_cleanup"] = cleanup_orphan_mpt_temp_files() >= 0
        except Exception:
            results["orphan_cleanup"] = False
    try:
        results["moviepy_unique_temp"] = patch_moviepy_write_videofile()
    except Exception:
        results["moviepy_unique_temp"] = False
    try:
        _install_post_import_hook()
        results["post_import_hook"] = True
    except Exception:
        results["post_import_hook"] = False
    _APPLIED = True
    _APPLY_RESULTS = results
    return dict(results)
