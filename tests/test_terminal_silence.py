"""1.1.00 — FIM DO LIXO NO TERMINAL (7.º relato do utilizador).

Prova COMPORTAMENTAL (não strings soltas): monta os handlers REAIS e captura o
stderr para mostrar que a telemetria de progresso sai do terminal, que os erros
reais ficam, e que tudo continua escrito em ficheiro para auditoria.

Cobre:
1. `[YT-AUTOM]` (`app/main.py`) — telemetria da aba Automação;
2. `[SCRIPT]`/`[PEXELS]`/`[MPT-*]` (`hermes_ui/pipeline_worker.py`) — telemetria
   do motor;
3. o aviso de terminal do `scripts/cli.mjs`;
4. a rota de escape `THUNDERBOLT_DEBUG=1`.

Cada teste usa um logger com nome único (injectado no módulo real), para que a
configuração dos handlers não seja poluída por outros testes da suite.
"""

from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
WORKER_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")


class _Capturado:
    """Contexto que troca sys.stderr por um buffer e devolve o texto."""

    def __enter__(self) -> io.StringIO:
        self._anterior = sys.stderr
        self.buffer = io.StringIO()
        sys.stderr = self.buffer
        return self.buffer

    def __exit__(self, *exc) -> None:
        sys.stderr = self._anterior


def _handlers_por_tipo(logger: logging.Logger) -> dict[str, list[logging.Handler]]:
    """Só os handlers do THUNDERBOLT contam.

    O pytest liga os seus próprios `LogCaptureHandler` (que também são
    `StreamHandler`) aos loggers da suite; contá-los faria o teste medir o
    framework em vez do nosso código. Os nossos estão marcados.
    """
    tipos: dict[str, list[logging.Handler]] = {"file": [], "stream": [], "outro": []}
    for handler in logger.handlers:
        if not getattr(handler, "_thunderbolt_automation_handler", False) and not getattr(
            handler, "_thunderbolt_mpt_handler", False
        ):
            continue  # handler de terceiros (pytest, bibliotecas): ignorado
        if isinstance(handler, logging.FileHandler):
            tipos["file"].append(handler)
        elif isinstance(handler, logging.StreamHandler):
            tipos["stream"].append(handler)
        else:
            tipos["outro"].append(handler)
    return tipos


# ---------------------------------------------------------------------------
# 1. telemetria do motor ([SCRIPT], [PEXELS], [MPT-*])
# ---------------------------------------------------------------------------


@pytest.fixture()
def mpt(tmp_path, monkeypatch):
    """O módulo real do pipeline_worker com um logger isolado e storage em tmp."""
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.delenv("THUNDERBOLT_DEBUG", raising=False)
    import hermes_ui.pipeline_worker as worker

    monkeypatch.setattr(worker, "STORAGE", tmp_path / "storage", raising=False)
    # nome único: nenhum handler de outro teste pode poluir esta configuração
    isolado = logging.getLogger(f"thunderbolt.mpt.teste.{tmp_path.name}")
    isolado.propagate = False
    isolado.setLevel(logging.INFO)
    monkeypatch.setattr(worker, "_mpt_logger", isolado, raising=False)
    return worker, tmp_path / "storage" / "logs" / "mpt_runtime.log"


def test_progress_telemetry_leaves_the_terminal(mpt):
    """`[SCRIPT] tentativa 1/3` e companhia NÃO aparecem no terminal."""
    worker, log_file = mpt
    with _Capturado() as stderr:
        worker._mpt_runtime_log("[SCRIPT] tarefa video_1: tentativa 1/3 - a chamar o LLM")
        worker._mpt_runtime_log("[PEXELS] Clipe 1/9 baixado com sucesso (tempo: 2.1s)")
        worker._mpt_runtime_log("[MPT-GATE] task=video_1 obteve slot (1/6)")
        worker._mpt_runtime_log("[MPT-SUBTITLES] queima local concluída em final-1.mp4")
    conteudo = stderr.getvalue()
    for trecho in ("[SCRIPT]", "[PEXELS]", "[MPT-GATE]", "[MPT-SUBTITLES]"):
        assert trecho not in conteudo, f"{trecho} não devia aparecer no terminal"
    # ...mas ficaram guardadas em ficheiro, para auditoria
    assert log_file.is_file()
    gravado = log_file.read_text(encoding="utf-8")
    assert "[SCRIPT] tarefa video_1: tentativa 1/3" in gravado
    assert "[PEXELS] Clipe 1/9" in gravado
    assert "[MPT-GATE]" in gravado
    assert "[MPT-SUBTITLES] queima local concluída" in gravado


def test_real_errors_stay_on_the_terminal(mpt):
    """Erros e avisos reais continuam visíveis — o terminal não ficou mudo."""
    worker, log_file = mpt
    with _Capturado() as stderr:
        worker._mpt_runtime_error("[MPT-SUBTITLES] [ERRO] falha na queima local (WinError 32)")
    conteudo = stderr.getvalue()
    assert "[MPT-SUBTITLES] [ERRO]" in conteudo
    assert "WinError 32" in conteudo
    # e também no ficheiro
    assert "[MPT-SUBTITLES] [ERRO]" in log_file.read_text(encoding="utf-8")


def test_debug_flag_restores_the_progress_on_the_terminal(mpt, monkeypatch):
    """THUNDERBOLT_DEBUG=1 é a rota de escape: a telemetria volta ao ecrã."""
    monkeypatch.setenv("THUNDERBOLT_DEBUG", "1")
    worker, log_file = mpt
    with _Capturado() as stderr:
        worker._mpt_runtime_log("[SCRIPT] tarefa video_1: tentativa 2/3")
    assert "[SCRIPT] tarefa video_1: tentativa 2/3" in stderr.getvalue()
    # e o ficheiro continua a receber tudo
    assert "[SCRIPT] tarefa video_1: tentativa 2/3" in log_file.read_text(encoding="utf-8")


def test_terminal_handler_sits_at_warning_outside_debug(mpt):
    """Fora de debug, o handler de terminal filtra INFO (só passa WARNING+)."""
    worker, _log_file = mpt
    worker._mpt_runtime_log("[MPT-TOTAL] uma linha para criar os handlers")
    tipos = _handlers_por_tipo(worker._mpt_logger)
    assert len(tipos["file"]) == 1
    assert len(tipos["stream"]) == 1
    assert tipos["stream"][0].level == logging.WARNING


def test_handlers_are_not_duplicated(mpt):
    """Criar o logger várias vezes não duplica linhas nem handlers."""
    worker, log_file = mpt
    with _Capturado() as stderr:
        worker._mpt_runtime_log("[MPT-TOTAL] primeira")
        worker._mpt_runtime_log("[MPT-TOTAL] segunda")
        worker._mpt_runtime_log("[MPT-TOTAL] terceira")
        tipos = _handlers_por_tipo(worker._mpt_logger)
    assert len(tipos["file"]) == 1, "handler de ficheiro duplicado"
    assert len(tipos["stream"]) == 1, "handler de terminal duplicado"
    assert log_file.read_text(encoding="utf-8").count("[MPT-TOTAL]") == 3
    assert "[MPT-TOTAL]" not in stderr.getvalue()


# ---------------------------------------------------------------------------
# 2. telemetria da aba Automação ([YT-AUTOM])
# ---------------------------------------------------------------------------


@pytest.fixture()
def yt_autom(tmp_path, monkeypatch):
    """O app/main real com um logger isolado e storage em tmp."""
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.delenv("THUNDERBOLT_DEBUG", raising=False)
    import app.main as main_module

    isolado = logging.getLogger(f"thunderbolt.automation.teste.{tmp_path.name}")
    isolado.propagate = False
    isolado.setLevel(logging.INFO)
    monkeypatch.setattr(main_module, "_automation_logger", isolado, raising=False)
    return main_module, tmp_path / "storage" / "logs" / "automation.log"


def test_yt_autom_telemetry_leaves_the_terminal(yt_autom):
    main_module, log_file = yt_autom
    with _Capturado() as stderr:
        main_module._ensure_automation_logger_handlers()
        main_module._automation_logger.info("[YT-AUTOM] sync roteiros: 0.01s")
        main_module._automation_logger.info("[YT-AUTOM] KPIs: 0.02s")
        main_module._automation_logger.info("[YT-AUTOM] task cards: 0.05s")
    assert "[YT-AUTOM]" not in stderr.getvalue()
    assert log_file.is_file()
    gravado = log_file.read_text(encoding="utf-8")
    assert "[YT-AUTOM] sync roteiros: 0.01s" in gravado
    assert "[YT-AUTOM] KPIs: 0.02s" in gravado
    assert "[YT-AUTOM] task cards: 0.05s" in gravado


def test_yt_autom_debug_flag_restores_the_terminal(yt_autom, monkeypatch):
    monkeypatch.setenv("THUNDERBOLT_DEBUG", "1")
    main_module, log_file = yt_autom
    with _Capturado() as stderr:
        main_module._ensure_automation_logger_handlers()
        main_module._automation_logger.info("[YT-AUTOM] channel cards: 0.03s")
    assert "[YT-AUTOM] channel cards: 0.03s" in stderr.getvalue()
    assert "[YT-AUTOM] channel cards: 0.03s" in log_file.read_text(encoding="utf-8")


def test_yt_autom_has_no_stream_handler_outside_debug(yt_autom):
    """Fora de debug a telemetria da aba não tem NENHUM handler de terminal."""
    main_module, _log_file = yt_autom
    main_module._ensure_automation_logger_handlers()
    tipos = _handlers_por_tipo(main_module._automation_logger)
    assert len(tipos["file"]) == 1
    assert len(tipos["stream"]) == 0


def test_yt_autom_survives_a_foreign_handler_on_the_logger(yt_autom):
    """Um handler de terceiro no logger não pode calar a telemetria.

    Regressão encontrada a meio deste trabalho: a guarda era «se já existe
    algum handler, sai» — o pytest (e qualquer biblioteca) liga handlers aos
    loggers, e a telemetria desaparecia em silêncio, o modo de faluto que a
    1.0.05 documentou. Agora a guarda reconhece os handlers pelos marcadores.
    """
    main_module, log_file = yt_autom
    intruso = logging.StreamHandler(io.StringIO())
    main_module._automation_logger.addHandler(intruso)
    try:
        main_module._ensure_automation_logger_handlers()
        tipos = _handlers_por_tipo(main_module._automation_logger)
        assert len(tipos["file"]) == 1, "handler de ficheiro não foi criado"
        main_module._automation_logger.info("[YT-AUTOM] com intruso: 0.01s")
        assert log_file.is_file()
        assert "[YT-AUTOM] com intruso" in log_file.read_text(encoding="utf-8")
    finally:
        main_module._automation_logger.removeHandler(intruso)


# ---------------------------------------------------------------------------
# 3. cli.mjs - o aviso de terminal
# ---------------------------------------------------------------------------


def test_launcher_prints_no_terminal_advisory():
    assert "nota de terminal" not in CLI_SOURCE
    assert "pode devolver o prompt sozinho" not in CLI_SOURCE
    # uma única linha útil no arranque: a URL
    arranque = [
        linha for linha in CLI_SOURCE.splitlines()
        if "interface disponível em http://localhost" in linha and "console.log" in linha
    ]
    assert len(arranque) == 1


def test_terminal_advisory_function_is_silent_but_keeps_telemetry():
    inicio = CLI_SOURCE.find("function launchTerminalAdvisory()")
    assert inicio != -1
    bloco = CLI_SOURCE[inicio:].split("\nfunction ", 1)[0]
    assert "console.log(" not in bloco
    assert "launchingFromSignalHeavyTerminal()" in bloco
    assert "terminal_sinal_pesado_detectado" in bloco


# ---------------------------------------------------------------------------
# 4. contratos de origem (o que não pode regressar)
# ---------------------------------------------------------------------------


def test_no_progress_print_left_in_the_worker_telemetry():
    """O print cru de legendas saiu; a falha passa pelo logger com nível."""
    assert 'print(f"[pexels] legendas ignoradas' not in WORKER_SOURCE
    assert "_mpt_runtime_error(" in WORKER_SOURCE


def test_automation_worker_keeps_its_real_error_messages():
    """O worker de automação continua a reportar erros e lotes criados."""
    worker = (ROOT / "hermes_ui" / "automation_worker.py").read_text(encoding="utf-8")
    assert 'print(f"Thunderbolt worker: erro:' in worker
    assert 'print(f"Thunderbolt worker: {len(result' in worker


def test_stream_handler_level_separates_noise_from_errors():
    """O handler de terminal do motor está em WARNING fora de debug."""
    bloco = WORKER_SOURCE.split("def _ensure_mpt_logger_handlers()", 1)[1].split("\ndef ", 1)[0]
    assert "logging.WARNING" in bloco
    assert "THUNDERBOLT_DEBUG" in bloco
    assert "mpt_runtime.log" in bloco


def test_automation_logger_uses_a_file_handler():
    bloco = MAIN_SOURCE.split("def _ensure_automation_logger_handlers()", 1)[1].split("\ndef ", 1)[0]
    assert "automation.log" in bloco
    assert "THUNDERBOLT_DEBUG" in bloco
    # o StreamHandler existe, mas DENTRO da guarda de debug
    stream = bloco.split("THUNDERBOLT_DEBUG", 1)[1]
    assert "StreamHandler" in stream
    # e a guarda reconhece os handlers pelos marcadores (não por "existe algum")
    assert "_thunderbolt_automation_handler" in bloco
    assert "if _automation_logger.handlers:" not in bloco


def test_terminal_advisory_note_is_gone_from_the_launcher_source():
    assert "nota de terminal" not in CLI_SOURCE


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))