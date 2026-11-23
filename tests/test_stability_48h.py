"""Estabilidade de sess longa (1.1.14): chave duplicada, fragmentos e OOM.

O relato: 48 horas de uso contínuo e o processo foi encerrado sozinho, com o
terminal inundado de `StreamlitDuplicateElementKey` e de avisos de fragmento
evicto. Aqui ficam os contratos das quatro correcções — algumas são de fonte
(onde a garantia é textual) e uma é FUNCIONAL: o dedupe corre a sério.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CLI_SOURCE = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
CONFIG_SOURCE = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")


# ------------------------------------------------------------- aviso de fragmento

def test_fragment_logger_is_silenced_alongside_the_app_session_one():
    """O ruído do fragmento evicto sai pelos DOIS loggers da 1.65."""
    assert 'logging.getLogger("streamlit.runtime.fragment")' in MAIN_SOURCE
    assert 'logging.getLogger("streamlit.runtime.app_session")' in MAIN_SOURCE
    # o filtro é o MECANISMO (não um setLevel que calaria erros verdadeiros) e
    # está ligado nos dois loggers
    assert MAIN_SOURCE.count("addFilter(_FragmentGoneNoiseFilter())") == 2


def test_the_filter_only_drops_the_known_race_line():
    """Não pode ser um silenciamento geral: só essa linha é descartada."""
    bloco = MAIN_SOURCE.split("class _FragmentGoneNoiseFilter", 1)[1].split("class ", 1)[0]
    assert '"does not exist anymore" not in record.getMessage()' in bloco
    assert "return False" not in bloco  # nunca descarta tudo


# ----------------------------------------------------------- chave duplicada

def test_the_task_lists_are_deduped_by_id():
    """As duas listas (YouTube e TikTok) deduplicam antes de renderizar."""
    assert "def _dedupe_automation_tasks(" in MAIN_SOURCE
    youtube = MAIN_SOURCE.split("def _render_youtube_automation_task_list", 1)[1].split("\ndef ", 1)[0]
    tiktok = MAIN_SOURCE.split("def _render_tiktok_automation_task_list", 1)[1].split("\ndef ", 1)[0]
    assert "_dedupe_automation_tasks(" in youtube
    assert "_dedupe_automation_tasks(" in tiktok
    # o dedupe acontece ANTES da paginação (senão a página ainda viria com duplicados)
    assert youtube.index("_dedupe_automation_tasks(") < youtube.index("page_size = 12")


def test_the_dedupe_keeps_the_first_of_each_id_and_drops_the_rest():
    """Prova funcional: a função corre a sério, não é só uma menção na fonte."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "tb_dedupe_probe", ROOT / "app" / "main.py"
    )
    # importar o main.py inteiro arrancaria o Streamlit; extrai-se só a função
    inicio = MAIN_SOURCE.index("def _dedupe_automation_tasks(")
    corpo = MAIN_SOURCE[inicio : MAIN_SOURCE.index("\ndef ", inicio + 10)]
    namespace: dict[str, object] = {"Any": object}
    exec("from typing import Any\n" + corpo, namespace)
    dedupe = namespace["_dedupe_automation_tasks"]

    tarefas = [
        {"id": "a", "topic": "um"},
        {"id": "b", "topic": "dois"},
        {"id": "a", "topic": "repetido"},
        {"id": "", "topic": "sem id"},
        {"id": "c", "topic": "tres"},
    ]
    resultado = dedupe(tarefas)
    assert [t["id"] for t in resultado] == ["a", "b", "c"]
    assert resultado[0]["topic"] == "um"  # ficou a PRIMEIRA ocorrência


def test_download_button_keys_stay_per_task():
    """A chave continua única por tarefa — o dedupe é o que garante o 1-por-card."""
    assert 'key=f"automation_download_thumbnail_{task[\'id\']}"' in MAIN_SOURCE
    assert 'key=f"tiktok_automation_download_thumbnail_{task_id}"' in MAIN_SOURCE
    # o dispatch live/idle continua a ser um if/else (uma variante por passo)
    lista = MAIN_SOURCE.split("def _render_youtube_automation_task_list", 1)[1].split("\ndef ", 1)[0]
    assert "if _catalog_task_state(task) in _VIDEO_TASK_LIVE_STATES:" in lista
    assert "_youtube_task_card_live(task_id)" in lista
    assert "_youtube_task_card_idle(task_id)" in lista


# ------------------------------------------------------------------- memória

def test_automation_log_rotates_instead_of_growing_forever():
    """48 h de telemetria a cada 3 s não pode encher o disco do utilizador."""
    bloco = MAIN_SOURCE.split("def _ensure_automation_logger_handlers", 1)[1].split("\ndef ", 1)[0]
    assert "logging.handlers.RotatingFileHandler(" in bloco
    assert "maxBytes=5 * 1024 * 1024" in bloco
    assert "backupCount=3" in bloco
    assert "import logging.handlers" in MAIN_SOURCE
    # o handler continua marcado (senão a telemetria desapareceria em silêncio)
    assert "_thunderbolt_automation_handler = True" in bloco


def test_streamlit_debug_logging_is_capped():
    assert '[logger]' in CONFIG_SOURCE
    assert 'level = "error"' in CONFIG_SOURCE
    # e o launcher injecta o mesmo por ambiente (vale para a cópia em storage/)
    assert 'STREAMLIT_LOGGER_LEVEL: "error"' in CLI_SOURCE


def test_no_unbounded_session_state_accumulation_in_the_cards():
    """Os cartões escrevem chaves por tarefa (limitadas), não listas sem fim."""
    card = MAIN_SOURCE.split("def _youtube_task_card_body", 1)[1].split("\ndef ", 1)[0]
    assert ".append(" not in card
    assert "st.session_state.setdefault" not in card


# ----------------------------------------------------------- watchdog de OOM

def test_launcher_restarts_the_server_after_an_oom_death():
    assert "[SISTEMA] O servidor caiu (OOM). A reiniciar em 5 segundos..." in CLI_SOURCE
    assert "streamlitOomSeen" in CLI_SOURCE
    # detecta pelos três sinais: rasto no stderr, código 137 e SIGKILL
    assert "code === 137" in CLI_SOURCE
    assert 'signal === "SIGKILL"' in CLI_SOURCE
    assert "memoryerror|out of memory|cannot allocate memory" in CLI_SOURCE
    # 5 segundos, e não o backoff exponencial
    assert "}, 5000);" in CLI_SOURCE
    # continua a contar para o disjuntor: um OOM em loop tem de parar a
    # recuperação, como qualquer outra falha
    ramo = CLI_SOURCE.split("[SISTEMA] O servidor caiu (OOM)", 1)[1].split("}, 5000);", 1)[0]
    assert "streamlitFailureCount += 1;" in ramo
    assert "streamlitOomSeen = false;" in ramo


def test_the_oom_flag_is_reset_between_lives():
    assert "streamlitOomSeen = false;" in CLI_SOURCE


def test_the_watchdog_keeps_the_existing_spawn_rules():
    """A regra inviolável do launcher não pode ser quebrada pela correcção."""
    # o spawn do SERVIDOR (não o respawn de actualização, que vive no handler
    # de saída e tem a excepção documentada de `detached` + `stdio: "ignore"`)
    spawn = CLI_SOURCE.split("child = spawn(python, [streamlitBootstrap", 1)[1].split(");", 1)[0]
    assert "windowsHide: true" in spawn
    assert "creationFlags: workerCreationFlags()," in spawn
    assert 'stdio: ["ignore", "pipe", "pipe"]' in spawn
    assert "detached: true" not in spawn
    # a reposição por OOM usa o mesmo caminho (sem consola visível)
    assert "windowsHide: true" in CLI_SOURCE