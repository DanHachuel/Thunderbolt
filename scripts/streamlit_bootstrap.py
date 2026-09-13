from __future__ import annotations

import io
import logging
import os
import signal
import sys

# Este ficheiro é o primeiro módulo Python executado pelo launcher. As
# variáveis e os streams precisam de ser corrigidos antes de qualquer import
# de streamlit/click, pois o erro utf-16-le acontece durante essa inicialização.
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONLEGACYWINDOWSSTDIO"] = "1"
os.environ["CLICK_NO_WIN_CONSOLE"] = "1"


# O shutdown do Streamlit pode emitir tracebacks assíncronos depois de SIGINT.
# Estes níveis só afectam a saída de encerramento, não os logs da aplicação.
logging.getLogger("uvicorn").setLevel(logging.CRITICAL)
logging.getLogger("streamlit").setLevel(logging.CRITICAL)


def _utf8_stream(stream: object) -> object:
    if os.name != "nt":
        return stream
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        return stream
    try:
        return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, OSError, ValueError):
        return stream


sys.stdout = _utf8_stream(sys.stdout)
sys.stderr = _utf8_stream(sys.stderr)


def _custom_sigint_handler(signum: int, frame: object) -> None:
    """Ignore Ctrl+C propagado pela consola para preservar a automação."""
    print("\nSIGINT ignorado: o Thunderbolt continua activo durante a automação.", file=sys.stderr, flush=True)


_original_signal = signal.signal


def _protected_signal(signum: signal.Signals, handler: object) -> object:
    """Não permitir que Streamlit substitua o handler seguro de SIGINT."""
    if signum == signal.SIGINT:
        return _original_signal(signal.SIGINT, _custom_sigint_handler)
    return _original_signal(signum, handler)


_original_signal(signal.SIGINT, _custom_sigint_handler)
signal.signal = _protected_signal

from streamlit.web.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
