"""Crashes de subprocessos no Windows + PermissionError nos logs (1.0.18).

1. `_read_log_text` (`app/main.py`): o Windows nega a leitura de um .log
   aberto em escrita pelo MoneyPrinterTurbo (PermissionError) — a página
   inteira de Logs morria com um único download por linha da tabela. Agora há
   uma 2ª leitura após 0,1s e, se continuar bloqueado, o download devolve um
   aviso em texto (o botão nunca quebra a UI).
2. `startQueueWorkers` (`scripts/cli.mjs`): os workers de fila deixam de
   herdar a consola do launcher — «stdio: "inherit"» crashava no Windows com
   «Fatal Python error: init_sys_streams» no arranque de 2 interpretadores em
   simultâneo, matando os workers no boot (loop de «a reiniciar em 5s»).
   Pipes + espelho na consola + logs próprios em storage/logs/*.log.
3. `record_worker_crash` (`hermes_ui/queue_worker_runtime.py`): o crash de
   um worker de fila deixa o traceback completo em
   `storage/logs/worker_crash.log` antes de sair — o reinício deixa de ser
   mudo e sem diagnóstico.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import app.main as main
from hermes_ui import image_worker, queue_worker_runtime, thumbnail_worker


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

LOCKED_LOG_MESSAGE = "O arquivo de log está a ser escrito por outro processo. Tente novamente em alguns segundos."


# ---------------------------------------------------------------------------
# 1. Logs: PermissionError nunca mais quebra a página
# ---------------------------------------------------------------------------


def test_read_log_text_reads_a_free_log_normally(tmp_path):
    log = tmp_path / "run-codigo.log"
    log.write_text("linha 1\nlinha 2\n", encoding="utf-8")
    assert main._read_log_text(log) == "linha 1\nlinha 2\n"


def test_read_log_text_returns_the_friendly_message_when_windows_keeps_the_file_locked(monkeypatch, tmp_path):
    log = tmp_path / "run-codigo.log"
    log.write_text("conteúdo", encoding="utf-8")

    def always_locked(self, *args, **kwargs):
        raise PermissionError(13, " Permission denied")

    monkeypatch.setattr(Path, "read_text", always_locked)
    assert main._read_log_text(log) == LOCKED_LOG_MESSAGE


def test_read_log_text_retries_once_before_giving_up(monkeypatch, tmp_path):
    log = tmp_path / "run-codigo.log"
    log.write_text("conteúdo", encoding="utf-8")
    attempts = {"count": 0}

    def flaky_read_text(self, *args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PermissionError(13, " Permission denied")
        return "leitura na 2ª tentativa"

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert main._read_log_text(log) == "leitura na 2ª tentativa"
    assert attempts["count"] == 2


def test_read_log_text_survives_a_vanished_log(monkeypatch, tmp_path):
    def gone_read_text(self, *args, **kwargs):
        raise FileNotFoundError(2, "sem ficheiro")

    monkeypatch.setattr(Path, "read_text", gone_read_text)
    message = main._read_log_text(tmp_path / "apagado.log")
    assert "Não foi possível ler o ficheiro de log" in message


def test_log_download_uses_the_tolerant_reader():
    logs_block = APP_SOURCE.split("def _log_download(", 1)[1].split("log_source = _log_source()", 1)[0]
    assert "content = _read_log_text(file_path)" in logs_block
    assert "file_path.read_text(" not in logs_block


# ---------------------------------------------------------------------------
# 2. Launcher: pipes + log próprio para os workers de fila
# ---------------------------------------------------------------------------


def _queue_block() -> str:
    return LAUNCHER_SOURCE.split("function startQueueWorkers()", 1)[1].split("function stopQueueWorkers()", 1)[0]


def test_queue_workers_no_longer_inherit_the_console():
    block = _queue_block()
    # 2 spawns, ambos com pipes válidos (stdin ignore) — herdar a consola era
    # a causa do «Fatal Python error: init_sys_streams» no arranque.
    assert block.count('stdio: ["ignore", "pipe", "pipe"]') == 2
    assert 'stdio: "inherit"' not in block
    # os comandos/estado exigidos pelos testes existentes continuam intactos
    assert '"-m", "hermes_ui.thumbnail_worker"' in block
    assert '"-m", "hermes_ui.image_worker"' in block


def test_queue_workers_log_to_dedicated_files():
    block = _queue_block()
    assert 'attachQueueWorkerLog(thumbnailWorker, "thumbnail_worker.log"' in block
    assert 'attachQueueWorkerLog(imageWorker, "image_worker.log"' in block
    helper = LAUNCHER_SOURCE.split("function attachQueueWorkerLog(", 1)[1].split("function startQueueWorkers()", 1)[0]
    # os logs vivem em storage/logs e a rotação limita o crescimento.
    assert 'join(storageDir, "logs")' in helper
    assert "statSync" in helper and "appendFileSync" in helper
    # espelho na consola: os crashes continuam visíveis no terminal do launcher.
    assert "process.stderr.write(chunk)" in helper


def test_queue_worker_log_survives_launcher_restart_without_console_handles():
    """O streamlit usa pipes desde sempre (funciona); os workers de fila
    passam a usar O MESMO padrão — pipes são sempre handles válidos."""
    assert 'stdio: ["ignore", "pipe", "pipe"]' in LAUNCHER_SOURCE.split("function startStreamlit()", 1)[1][:600]


# ---------------------------------------------------------------------------
# 3. Crash de worker: traceback persistido antes de morrer
# ---------------------------------------------------------------------------


@pytest.fixture()
def crash_log(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "worker_crash.log"
    monkeypatch.setattr(queue_worker_runtime, "worker_crash_log_path", lambda: path)
    return path


def test_record_worker_crash_writes_the_full_traceback(crash_log):
    try:
        raise ValueError("falha na geração da imagem")
    except ValueError:
        queue_worker_runtime.record_worker_crash("thumbnail_worker")
    content = crash_log.read_text(encoding="utf-8")
    assert "Crash no worker (thumbnail_worker)" in content
    assert "ValueError: falha na geração da imagem" in content


@pytest.mark.parametrize("worker_module,worker_label", [(thumbnail_worker, "thumbnail_worker"), (image_worker, "image_worker")])
def test_run_worker_persists_the_crash_before_exiting(monkeypatch, crash_log, worker_module, worker_label):
    monkeypatch.setattr("hermes_ui.storage.ensure_storage", lambda: None)
    monkeypatch.setattr(worker_module, "_heartbeat", lambda **updates: None)
    recover_name = "_recover_claims_from_previous_process" if worker_label == "thumbnail_worker" else "_recover_orphaned_claims"
    monkeypatch.setattr(worker_module, recover_name, lambda: None)

    def boom():
        raise RuntimeError("provider de imagem em panne")

    monkeypatch.setattr(worker_module, "run_once", boom)
    with pytest.raises(SystemExit) as exit_info:
        worker_module.run_worker(interval_seconds=2)
    assert exit_info.value.code == 1
    content = crash_log.read_text(encoding="utf-8")
    assert f"Crash no worker ({worker_label})" in content
    assert "RuntimeError: provider de imagem em panne" in content


def test_worker_sources_wire_the_crash_handler():
    thumbnail_block = (ROOT / "hermes_ui" / "thumbnail_worker.py").read_text(encoding="utf-8").split("def run_worker(", 1)[1].split("def main()", 1)[0]
    assert 'record_worker_crash("thumbnail_worker")' in thumbnail_block
    assert "raise SystemExit(1) from None" in thumbnail_block
    image_block = (ROOT / "hermes_ui" / "image_worker.py").read_text(encoding="utf-8").split("def run_worker(", 1)[1].split("def main()", 1)[0]
    assert 'record_worker_crash("image_worker")' in image_block
    assert "raise SystemExit(1) from None" in image_block
