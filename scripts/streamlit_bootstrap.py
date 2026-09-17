from __future__ import annotations

import io
import logging
import os
import signal
import sys
import warnings

# Este ficheiro é o primeiro módulo Python executado pelo launcher. As
# variáveis e os streams precisam de ser corrigidos antes de qualquer import
# de streamlit/click, pois o erro utf-16-le acontece durante essa inicialização.
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONLEGACYWINDOWSSTDIO"] = "1"
os.environ["CLICK_NO_WIN_CONSOLE"] = "1"

# O Streamlit emite este aviso quando o launcher inicializa o servidor fora
# do contexto de uma execução de script. É esperado neste modo de arranque;
# manter a filtragem direccionada para não ocultar outros warnings úteis.
warnings.filterwarnings("ignore", message=r".*missing ScriptRunContext.*")


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
    """SIGINT ignorado: não reentrar no ciclo do servidor via Ctrl+C."""
    return None


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
