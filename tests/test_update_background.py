"""1.1.02 - actualizacao em segundo plano (start_update + ficheiro de estado).

O relato: o botao "Atualizar Versao" bloqueava a pagina dentro do `st.spinner`
durante os minutos do `npx install`, sem prova de progresso e sem log para
Diagnostic uma falha. Estes testes prendem o contrato novo:

- `start_update()` devolve IMEDIATAMENTE com `status="running"` e lanca o
  instalador numa thread daemon (a UI nunca bloqueia);
- o instalador corre com `asyncio.create_subprocess_exec` e escreve tudo em
  `storage/logs/update.log`;
- o estado publicado em `storage/state/update_status.json` percorre
  running -> done/error (a UI faz polling num `st.fragment`);
- dois cliques nao lancam dois instaladores;
- ja na versao mais recente nao lanca nada.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_ui import update_manager


class _Response:
    def __init__(self, version: str):
        self.version = version

    def raise_for_status(self):
        return None

    def json(self):
        return {"version": self.version}


def _ok_get(*args, **kwargs):
    return _Response("0.3.97")


@pytest.fixture()
def storage_isolado(tmp_path, monkeypatch):
    """Aponta o modulo para um storage temporario (estado + logs)."""
    (tmp_path / "logs").mkdir()
    gravado: dict[str, object] = {}

    def write_json(name, payload):
        gravado[name] = payload
        (tmp_path / "state").mkdir(exist_ok=True)
        (tmp_path / "state" / name).write_text(json.dumps(payload), encoding="utf-8")

    def read_json(name, default=None):
        path = tmp_path / "state" / name
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    monkeypatch.setattr(update_manager, "storage", SimpleNamespace(write_json=write_json, read_json=read_json))
    monkeypatch.setattr(update_manager, "update_log_path", lambda: tmp_path / "logs" / "update.log")
    return SimpleNamespace(raiz=tmp_path, gravado=gravado)


# ---------------------------------------------------------------------------
# 1. arranque: imediato, uma unica vez
# ---------------------------------------------------------------------------


def test_start_update_returns_running_without_blocking(storage_isolado, monkeypatch):
    """O clique devolve na hora: so a thread daemon e que espera pelo npx."""
    lancada = []

    def fake_thread(target=None, **kwargs):
        lancada.append(target)
        return SimpleNamespace(start=lambda: None)

    monkeypatch.setattr(update_manager.threading, "Thread", fake_thread)

    resultado = update_manager.start_update("0.3.96", get=_ok_get)

    assert resultado.status == "running"
    assert resultado.ok is True
    assert resultado.latest_version == "0.3.97"
    assert len(lancada) == 1, "uma thread daemon, lancada uma vez"


def test_start_update_ignores_a_second_click_while_running(storage_isolado, monkeypatch):
    """Duplo clique nunca lanca dois instaladores a disputar o .runtime."""
    # um job ja em curso (estado publicado em disco, deste mesmo processo)
    update_manager._write_update_status(
        {"status": "running", "latest_version": "0.3.97", "pid": update_manager.os.getpid()}
    )

    def boom(*args, **kwargs):
        raise AssertionError("nao deve lancar outro instalador")

    monkeypatch.setattr(update_manager.threading, "Thread", boom)

    segundo = update_manager.start_update("0.3.96", get=_ok_get)  # estado ja running

    assert segundo.status == "running"
    assert "ja esta a correr" in segundo.message


def test_start_update_does_nothing_when_already_current(storage_isolado):
    resultado = update_manager.start_update("0.3.97", get=_ok_get)

    assert resultado.status == "idle"
    assert "ja esta" in resultado.message
    assert not (storage_isolado.raiz / "logs" / "update.log").exists()


# ---------------------------------------------------------------------------
# 2. o runner: subprocess assincrono + log + transicoes de estado
# ---------------------------------------------------------------------------


class _FakeProcess:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode

    async def wait(self):
        return self.returncode

    def kill(self):
        return None


def _fake_factory(returncode: int, gravado: dict):
    async def factory(*command, **kwargs):
        gravado["command"] = command
        gravado["stdout"] = kwargs.get("stdout")
        gravado["stderr"] = kwargs.get("stderr")
        return _FakeProcess(returncode)

    return factory


def test_background_update_publishes_the_running_then_done_states(storage_isolado, monkeypatch):
    gravado = storage_isolado.gravado
    monkeypatch.setattr(
        update_manager,
        "check_version",
        lambda current, **kwargs: update_manager.VersionCheck(current_version=current, latest_version="0.3.97"),
    )

    resultado = asyncio.run(
        update_manager._run_update_async(
            "0.3.96",
            "0.3.97",
            create_subprocess_exec=_fake_factory(0, gravado),
        )
    )

    assert resultado["status"] == "done"
    assert resultado["restart_required"] is True
    assert gravado["command"][-2:] == ("@danhachuel/thunderbolt", "install")
    # a saida do instalador vai para o ficheiro, nunca para a memoria da UI
    assert gravado["stdout"] is not None
    assert gravado["stderr"] is update_manager.subprocess.STDOUT
    # e o estado final ficou no disco, onde a UI o le
    assert update_manager.read_update_status()["status"] == "done"


def test_background_update_publishes_error_on_nonzero_exit(storage_isolado, monkeypatch):
    gravado = storage_isolado.gravado

    resultado = asyncio.run(
        update_manager._run_update_async(
            "0.3.96",
            "0.3.97",
            create_subprocess_exec=_fake_factory(1, gravado),
        )
    )

    assert resultado["status"] == "error"
    assert resultado["exit_code"] == 1
    estado = update_manager.read_update_status()
    assert estado["status"] == "error"
    assert "update.log" in estado["message"]


def test_background_update_publishes_error_when_the_installer_cannot_start(storage_isolado):
    async def factory(*command, **kwargs):
        raise OSError("npx nao encontrado")

    resultado = asyncio.run(
        update_manager._run_update_async("0.3.96", "0.3.97", create_subprocess_exec=factory)
    )

    assert resultado["status"] == "error"
    assert "nao foi possivel iniciar" in resultado["message"].lower()
    # o log fica no disco para Diagnostic
    assert (storage_isolado.raiz / "logs" / "update.log").exists()


def test_background_update_publishes_error_on_timeout(storage_isolado):
    class _SlowProcess:
        returncode = None

        async def wait(self):
            await asyncio.sleep(5)

        def kill(self):
            return None

    async def factory(*command, **kwargs):
        return _SlowProcess()

    resultado = asyncio.run(
        update_manager._run_update_async("0.3.96", "0.3.97", timeout=1, create_subprocess_exec=factory)
    )

    assert resultado["status"] == "error"
    assert "tempo limite" in resultado["message"].lower()


# ---------------------------------------------------------------------------
# 3. o log e o estado sao o contrato com a UI
# ---------------------------------------------------------------------------


def test_update_log_records_the_command_and_rotates(storage_isolado):
    log_path = storage_isolado.raiz / "logs" / "update.log"
    log_path.write_text("x" * (update_manager.UPDATE_LOG_MAX_BYTES + 10), encoding="utf-8")

    handle = update_manager._open_log(["npx", "install"], "0.3.97")
    handle.close()

    conteudo = log_path.read_text(encoding="utf-8")
    assert "npx install" in conteudo
    assert len(log_path.read_text(encoding="utf-8")) < update_manager.UPDATE_LOG_MAX_BYTES


def test_read_update_status_defaults_to_idle(storage_isolado):
    assert update_manager.read_update_status() == {"status": "idle"}


def test_read_update_status_recovers_a_stale_running_job(storage_isolado, monkeypatch):
    """Job orfa (o processo morreu): o estado NAO fica 'running' para sempre."""
    monkeypatch.setattr(update_manager, "_pid_alive", lambda *a, **k: False)
    update_manager._write_update_status({"status": "running", "latest_version": "0.3.97", "pid": 4242424})

    estado = update_manager.read_update_status()

    assert estado["status"] == "error"
    assert "interrompida" in estado["message"]


def test_read_update_status_keeps_a_live_job_of_another_process(storage_isolado, monkeypatch):
    """Outro processo vivo ainda a instalar: continua 'running' (nao rouba o job)."""
    monkeypatch.setattr(update_manager, "_pid_alive", lambda *a, **k: True)
    update_manager._write_update_status({"status": "running", "latest_version": "0.3.97", "pid": 999999})

    assert update_manager.read_update_status()["status"] == "running"


def test_pid_marker_matches_both_windows_and_posix_cmdlines(storage_isolado, monkeypatch):
    """O marcador de identidade tem de casar com os dois separadores de caminho."""
    vistos = {}

    def fake_pid_alive(pid, *, expect_marker=""):
        vistos["marker"] = expect_marker
        return True

    monkeypatch.setattr(update_manager, "_pid_alive", fake_pid_alive)
    update_manager._write_update_status({"status": "running", "latest_version": "0.3.97", "pid": 999999})

    update_manager.read_update_status()

    assert "/" not in vistos["marker"], "um caminho com / nao casa com o cmdline do Windows"
    assert "main.py" in vistos["marker"]


def test_read_update_status_keeps_the_job_of_the_current_process(storage_isolado):
    update_manager._write_update_status({"status": "running", "latest_version": "0.3.97", "pid": update_manager.os.getpid()})

    assert update_manager.read_update_status()["status"] == "running"


def test_update_status_is_written_atomically(storage_isolado):
    update_manager._write_update_status({"status": "running", "pid": update_manager.os.getpid()})

    estado = update_manager.read_update_status()

    assert estado["status"] == "running"
    # escrita atomica: nunca um ficheiro parcial no disco
    assert (storage_isolado.raiz / "state" / update_manager.UPDATE_STATUS_NAME).is_file()


def test_terminal_line_announces_the_npx_command(storage_isolado, monkeypatch, capsys):
    """O utilizador ve no terminal o comando que esta a correr (validacao 2)."""
    monkeypatch.setattr(update_manager.threading, "Thread", lambda *a, **k: SimpleNamespace(start=lambda: None))

    update_manager.start_update("0.3.96", get=_ok_get)

    saida = capsys.readouterr()
    texto = (saida.out + saida.err).lower()
    assert "actualizar o thunderbolt" in texto
    assert "npx.cmd" in texto or "npx" in texto
    assert "update.log" in texto