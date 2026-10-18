import io
import logging
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


class AutomationLoggingTests(unittest.TestCase):
    """1.0.05: a telemetria [YT-AUTOM] não pode crashar com o stdout fechado.

    O print(flush=True) do _log crashava com "ValueError: I/O operation on
    closed file" quando o Streamlit fechava o sys.stdout durante um rerun
    (ex.: "Refazer vídeo"). O _log passa a emitir via logging num handler
    dedicado com referência estável ao stderr real da consola.
    """

    def test_log_uses_logging_instead_of_print_flush(self):
        block = MAIN_SOURCE.split("def render_automation():", 1)[1].split("def render_upload_direct():", 1)[0]
        self.assertNotIn('print(f"[YT-AUTOM]', block)
        self.assertIn('_automation_logger.info(f"[YT-AUTOM] {msg}', block)
        # Guarda: telemetria nunca interrompe o render, mesmo com o stream
        # do handler fechado.
        self.assertIn("except (ValueError, OSError):", block)

    def test_automation_logger_configured_at_module_level(self):
        # Logger dedicado com nome estável ("thunderbolt.automation"), nível
        # INFO (o lastResort só emite WARNING+ e engoliria a telemetria) e
        # handler próprio no stderr — sem propagação para o root.
        self.assertIn('logging.getLogger("thunderbolt.automation")', MAIN_SOURCE)
        self.assertIn("_automation_logger.setLevel(logging.INFO)", MAIN_SOURCE)
        self.assertIn("_automation_logger.propagate = False", MAIN_SOURCE)
        self.assertIn("logging.StreamHandler(sys.stderr)", MAIN_SOURCE)
        self.assertIn('if not _automation_logger.handlers:', MAIN_SOURCE)

    def test_automation_logger_runtime_shape(self):
        # O import de app.main já corre a configuração; o logger tem de
        # existir, estar em INFO e ter exatamente um handler que escreve.
        from app import main as app_main

        automation_logger = logging.getLogger("thunderbolt.automation")
        self.assertEqual(automation_logger.level, logging.INFO)
        self.assertFalse(automation_logger.propagate)
        self.assertTrue(automation_logger.handlers)
        self.assertIs(automation_logger, app_main._automation_logger)

    def test_logging_swallows_writes_to_closed_stream(self):
        # Runtime do mecanismo: mesmo que o stream do handler esteja
        # fechado, logger.info() não lança — o logging engole a falha de
        # escrita internamente (Handler.handleError).
        closed = io.StringIO()
        closed.close()
        handler = logging.StreamHandler(closed)
        probe = logging.getLogger("thunderbolt.automation.closed_stream_probe")
        probe.addHandler(handler)
        probe.setLevel(logging.INFO)
        probe.propagate = False
        previous_raise = logging.raiseExceptions
        logging.raiseExceptions = False  # silencia o relatório interno de logging
        try:
            probe.info("[YT-AUTOM] probe em stream fechado: 0.00s")
        finally:
            logging.raiseExceptions = previous_raise
            probe.removeHandler(handler)
            handler.close()

    def test_stable_handler_stream_survives_rerun_stdout_close(self):
        # Cenário do rerun do Streamlit: o stdout do script run morre, mas o
        # handler guarda referência estável ao stream da consola — a
        # telemetria continua a ser escrita depois do fecho.
        console = io.StringIO()
        handler = logging.StreamHandler(console)
        probe = logging.getLogger("thunderbolt.automation.stable_stream_probe")
        probe.addHandler(handler)
        probe.setLevel(logging.INFO)
        probe.propagate = False
        try:
            rerun_stdout = io.StringIO()
            probe.info("[YT-AUTOM] antes do rerun: 0.00s")
            rerun_stdout.close()  # o Streamlit fecha o stdout do script run
            with self.assertRaises(ValueError):
                rerun_stdout.write("boom")  # confirmar que o stdout morreu
            probe.info("[YT-AUTOM] depois do rerun: 0.01s")
            output = console.getvalue()
        finally:
            probe.removeHandler(handler)
            handler.close()
        self.assertIn("antes do rerun", output)
        self.assertIn("depois do rerun", output)


if __name__ == "__main__":
    unittest.main()
