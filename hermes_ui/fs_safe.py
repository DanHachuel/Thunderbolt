"""Operações de ficheiro tolerantes a bloqueios do Windows (WinError 32).

O MoviePy (motor MPT e a queima local de legendas) escreve ficheiros
temporários e apaga-os/move-os a seguir; no Windows o FFmpeg/Windows
Defender podem manter o handle aberto alguns instantes depois de o
processo filho sair — o ``os.replace``/``os.remove`` falha com
``[WinError 32] O arquivo já está sendo usado por outro processo`` (issue
#217 do MoneyPrinterTurbo, reproduzida nesta máquina a 25/10 14:35 na
queima de legendas). Este módulo concentra o retry com backoff para essas
operações — usado pela queima de legendas, pelo normalizador streamable e
por qualquer mov/remoção de artefacto.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable


# WinError 32 = ERROR_SHARING_VIOLATION ("o arquivo já está sendo usado").
WINDOWS_LOCK_ERROR = 32
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE_SECONDS = 0.5


def _is_lock_error(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == WINDOWS_LOCK_ERROR


def safe_file_op(
    operation_func: Callable[..., Any],
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    **kwargs: Any,
) -> Any:
    """Executa uma operação de ficheiro com retry em bloqueio do Windows.

    Backoff exponencial: 0.5 s, 1 s, 2 s, 4 s (5 tentativas por omissão).
    Qualquer outro erro (ou o erro 32 esgotado) propaga — a operação nunca
    falha em silêncio.
    """
    for attempt in range(max_retries):
        try:
            return operation_func(*args, **kwargs)
        except OSError as exc:
            if not _is_lock_error(exc) or attempt >= max_retries - 1:
                raise
            time.sleep(backoff_base_seconds * (2**attempt))
    # inalcançável: o ciclo acima propaga na última tentativa
    raise OSError("safe_file_op esgotou as tentativas sem resultado")


def safe_replace(source: Path | str, destination: Path | str, **kwargs: Any) -> Path:
    """``os.replace`` com retry em WinError 32 (substituição in-place segura)."""
    source_path = Path(source)
    destination_path = Path(destination)
    safe_file_op(os.replace, str(source_path), str(destination_path), **kwargs)
    return destination_path


def safe_unlink(path: Path | str, *, missing_ok: bool = True, **kwargs: Any) -> bool:
    """``Path.unlink`` com retry em WinError 32; devolve False se já não existe."""
    target = Path(path)
    if missing_ok and not target.exists():
        return False
    try:
        safe_file_op(target.unlink, missing_ok=missing_ok, **kwargs)
    except FileNotFoundError:
        if missing_ok:
            return False
        raise
    return True
