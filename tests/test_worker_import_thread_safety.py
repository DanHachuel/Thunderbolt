"""Regressão 1.0.81: os workers têm de poder ser importados fora da thread principal.

O Streamlit corre o script do utilizador numa THREAD SECUNDÁRIA. Os 4 workers
eram importados pelo `app/main.py` e faziam `signal.signal(...)` ao nível do
módulo — o que o Python só permite na thread principal. O resultado era
`ValueError: signal only works in main thread of the main interpreter` e a
interface INTEIRA deixava de renderizar (o sintoma foi relatado como
"thumbnails que desapareceram", porque sem UI não há cards).
"""
from __future__ import annotations

import importlib
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ("automation_worker", "pipeline_worker", "thumbnail_worker", "image_worker")


@pytest.fixture(scope="module")
def _import_workspace():
    sys.path.insert(0, str(ROOT))
    yield
    for name in WORKERS:
        sys.modules.pop(f"hermes_ui.{name}", None)


def _import_in_thread(module_name: str, results: dict) -> None:
    try:
        importlib.import_module(module_name)
        results[module_name] = "ok"
    except Exception as exc:  # noqa: BLE001
        results[module_name] = f"{type(exc).__name__}: {exc}"


@pytest.mark.parametrize("worker", WORKERS)
def test_worker_imports_inside_a_secondary_thread(_import_workspace, worker):
    """É exactamente o que o Streamlit faz: importar o worker numa thread."""
    results: dict[str, str] = {}
    thread = threading.Thread(target=_import_in_thread, args=(f"hermes_ui.{worker}", results))
    thread.start()
    thread.join(timeout=60)
    assert not thread.is_alive(), f"o import de {worker} bloqueou a thread"
    assert results.get(f"hermes_ui.{worker}") == "ok", results


@pytest.mark.parametrize("worker", WORKERS)
def test_worker_has_no_unprotected_signal_registration(worker):
    """Nenhum `signal.signal` desprotegido ao nível do módulo.

    A chamada legítima (blindagem de arranque) tem de vir dentro do bloco
    protegido pela guarda de thread principal — nunca solta no topo.
    """
    source = (ROOT / "hermes_ui" / f"{worker}.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith("signal.signal("):
            assert False, f"{worker}: signal.signal ao nível do módulo sem guarda"
    assert "threading.main_thread()" in source


@pytest.mark.parametrize("worker", WORKERS)
def test_worker_signal_guard_is_thread_safe(worker):
    """A blindagem do sinal tem de estar protegida pela guarda de thread.

    Sem a guarda, o import do worker pelo Streamlit (thread secundária) levanta
    `ValueError: signal only works in main thread of the main interpreter` e a
    interface inteira deixa de renderizar — o bug 1.0.81.
    """
    source = (ROOT / "hermes_ui" / f"{worker}.py").read_text(encoding="utf-8")
    assert 'if sys.platform == "win32" and threading.current_thread() is threading.main_thread():' in source
    assert "except ValueError:" in source  # e absorve o erro em último recurso
    assert "signal.signal(signal.SIGINT, signal.SIG_IGN)" in source
    assert "import threading" in source


def test_no_worker_registers_signals_at_import_time(_import_workspace):
    """Importar os 4 workers não pode crashar — é o que o Streamlit faz."""
    for worker in WORKERS:
        importlib.import_module(f"hermes_ui.{worker}")
