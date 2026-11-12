"""1.0.94 — regressões da auditoria global (Etapa 1 → Etapa 2).

Cobre as cinco correcções que não estavam cravas em lado nenhum:

1. `hasPendingPipelineWork` EXISTE em `app/main.py` — era chamada e exigida
   pelos testes, mas nunca foi definida: um `NameError` latente que só
   disparava sem marca de launcher e deixava a aba Automação sem renderizar.
2. `THUNDERBOLT_LAUNCHER_ACTIVE` é injectada pelo launcher e lida pela UI
   (`_launcher_activo`) — o banner amarelo de falso positivo nunca aparece
   para uma stack nascida do `npx`.
3. «Forçar Reinício do Sistema» tem caminho próprio quando não há launcher
   vivo (o pedido escrito ficaria no disco para sempre).
4. `_file_bytes` deixa de engolir vídeo: ficheiros grandes usam o
   mini-servidor HTTP local (zero RAM) ou o padrão «Preparar» — nunca
   `read_bytes()` a cada render.
5. O caminho Remotion passa pelo `sanitize_blueprint_for_prompt` (regra
   inviolável do AGENTS.md: regras de contagem de caracteres não vão à LLM).
6. As raízes servidas pelo mini-servidor incluem `storage/artifacts`, onde
   vivem os vídeos de tarefa — sem elas o player caía no `st.video(caminho)`
   e voltava o spinner infinito.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CLI = (ROOT / "scripts" / "cli.mjs").read_text(encoding="utf-8")
WORKER = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. hasPendingPipelineWork existir (o NameError latente)
# ---------------------------------------------------------------------------


def _function_source(name: str) -> str:
    """Código-fonte REAL (sem normalização) de uma função de topo de app/main.py."""
    for node in ast.parse(MAIN).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(MAIN, node)
            if segment:
                return segment
            break
    raise AssertionError(f"função {name} não encontrada em app/main.py")


def _run_main_function(name: str, namespace: dict):
    """Executa a função real de app/main.py num namespace mínimo (sem Streamlit)."""
    node = next(
        item for item in ast.parse(MAIN).body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    exec(compile(ast.unparse(node), f"<main.py:{name}>", "exec"), namespace)
    return namespace[name]


def test_pending_pipeline_work_helper_is_defined():
    """Era CHAMADA e exigida pelos testes, mas NUNCA existiu."""
    assert "def hasPendingPipelineWork(" in MAIN
    helper = _function_source("hasPendingPipelineWork")
    assert 'state in {"to_do", "doing"}' in helper


def test_pending_pipeline_work_helper_actually_works():
    """A função corre de verdade: sem tarefas = False, com fila = True."""
    consulta = _run_main_function(
        "hasPendingPipelineWork", {"read_json": lambda name, default=None: [], "Exception": Exception}
    )
    assert consulta() is False

    consulta = _run_main_function(
        "hasPendingPipelineWork",
        {"read_json": lambda name, default=None: [{"id": "1", "state": "done"}], "Exception": Exception},
    )
    assert consulta() is False

    consulta = _run_main_function(
        "hasPendingPipelineWork",
        {"read_json": lambda name, default=None: [{"id": "1", "state": "to_do"}], "Exception": Exception},
    )
    assert consulta() is True

    # schema legado: a UF usa `status`, não `state`
    consulta = _run_main_function(
        "hasPendingPipelineWork",
        {"read_json": lambda name, default=None: [{"id": "2", "status": "DOING"}], "Exception": Exception},
    )
    assert consulta() is True


# ---------------------------------------------------------------------------
# 2. THUNDERBOLT_LAUNCHER_ACTIVE: launcher injecta, UI lê
# ---------------------------------------------------------------------------


def test_launcher_injects_the_active_marker_for_every_child():
    assert 'THUNDERBOLT_LAUNCHER_ACTIVE: "1",' in CLI
    # жив no runtimeEnv, que alimenta o foreground E (por herança) os spawns
    # destacados: a marca chega ao servidor e aos 4 workers.
    runtime_env = CLI.split("const runtimeEnv = {", 1)[1].split("\n};", 1)[0]
    assert "THUNDERBOLT_LAUNCHER_ACTIVE" in runtime_env


def test_ui_reads_the_active_marker_to_kill_the_false_warning():
    helper = MAIN.split("def _launcher_activo(", 1)[1].split("\ndef ", 1)[0]
    assert 'os.environ.get("THUNDERBOLT_LAUNCHER_ACTIVE", "").strip() == "1"' in helper
    operacional = MAIN.split("def _worker_automation_operacional(", 1)[1].split("\ndef ", 1)[0]
    assert "return _launcher_activo()" in operacional


def test_manual_python_run_without_launcher_still_warns():
    """Sem marca e sem lock, o aviso continua — aí faz falta."""
    import os as _os
    import tempfile as _tempfile

    for variavel in ("THUNDERBOLT_LAUNCHER_ACTIVE", "THUNDERBOLT_LAUNCHER_MODE"):
        _os.environ.pop(variavel, None)
    activo = _run_main_function(
        "_launcher_activo",
        {"os": _os, "json": json, "STORAGE": Path(_tempfile.gettempdir()) / "tb-storage-inexistente"},
    )
    assert activo() is False
    for variavel in ("THUNDERBOLT_LAUNCHER_ACTIVE", "THUNDERBOLT_LAUNCHER_MODE"):
        _os.environ.pop(variavel, None)


# ---------------------------------------------------------------------------
# 3. Forçar Reinício sem launcher vivo
# ---------------------------------------------------------------------------


def test_force_restart_falls_back_to_the_ui_without_a_launcher():
    banner = MAIN.split("def _render_pipeline_worker_banner(", 1)[1].split("\ndef ", 1)[0]
    assert "_forcar_reinicio_dos_workers()" in banner
    assert "_launcher_activo()" in banner
    # as DUAS mensagens têm de existir: a do launcher vivo e a da UI que repõe
    assert "O launcher vai reiniciar os workers" in banner
    assert "Workers repostos pela interface" in banner


def test_ui_can_spawn_every_queue_worker():
    """Sem launcher, a UI repõe pipeline, thumbnails, imagens e automação."""
    helper = MAIN.split("def _forcar_reinicio_dos_workers(", 1)[1].split("\ndef ", 1)[0]
    for module in ("pipeline_worker", "thumbnail_worker", "image_worker"):
        assert f'_spawn_queue_worker("{module}"' in helper
    assert "_iniciar_worker_automacao_sob_demanda()" in helper
    assert "resume_pipeline_worker()" in helper  # a fila pausada é retomada
    spawner = MAIN.split("def _spawn_queue_worker(", 1)[1].split("\ndef ", 1)[0]
    # contrato stdio-seguro (igual ao do launcher): sem consola, grupo próprio
    assert "CREATE_NEW_PROCESS_GROUP" in spawner
    assert "CREATE_NO_WINDOW" in spawner
    assert "stdin=subprocess.DEVNULL" in spawner


# ---------------------------------------------------------------------------
# 4. Downloads de vídeo sem RAM
# ---------------------------------------------------------------------------


def test_file_bytes_refuses_large_files():
    """`_file_bytes` deixa de engolir vídeo (auditoria A3)."""
    helper = _function_source("_file_bytes")
    assert "_LARGE_FILE_BYTES" in helper
    assert "st_size > _LARGE_FILE_BYTES" in helper
    assert 'return b""' in helper
    # o cache pequeno continua (contrato 1.0.84 intacto)
    assert "@st.cache_data(show_spinner=False, max_entries=256)" in MAIN
    assert "def _cached_file_bytes(" in MAIN


def test_file_bytes_returns_empty_for_a_large_video(tmp_path):
    """Prova funcional: um MP4 grande nunca entra no cache nem na RAM."""
    grande = tmp_path / "video.webm"
    grande.write_bytes(b"x" * (8 * 1024 * 1024 + 1))  # um byte acima do limite
    namespace: dict = {
        "_LARGE_FILE_BYTES": 8 * 1024 * 1024,
        "Path": Path,
        "_cached_file_bytes": lambda *args: b"NUNCA",
    }
    consulta = _run_main_function("_file_bytes", namespace)
    assert consulta(grande) == b""


def test_file_bytes_still_reads_small_files(tmp_path):
    """O contrato 1.0.84 (thumbnails/prompts/roteiros) fica intacto."""
    pequeno = tmp_path / "thumb.png"
    pequeno.write_bytes(b"png")
    namespace: dict = {
        "_LARGE_FILE_BYTES": 8 * 1024 * 1024,
        "Path": Path,
        "_cached_file_bytes": lambda *args: b"png",
    }
    consulta = _run_main_function("_file_bytes", namespace)
    assert consulta(pequeno) == b"png"
    assert consulta(tmp_path / "nao-existe.png") == b""


def test_video_download_prefers_the_local_http_server():
    helper = MAIN.split("def _render_video_download_control(", 1)[1].split("\ndef ", 1)[0]
    assert "_tb_media_local_url(video_path)" in helper
    assert 'download="{safe_name}"' in helper
    # rede de segurança: ficheiro fora das raízes servidas → «Preparar»
    assert "Preparar Vídeo para download" in helper
    assert "video_path.open(\"rb\")" in helper


def test_no_card_reads_a_video_into_the_cache_anymore():
    assert "data=_file_bytes(video_path)" not in MAIN
    for card in (
        MAIN.split("def _render_tiktok_automation_task_list", 1)[1].split("def render_tiktok_automation", 1)[0],
        MAIN.split("def _render_bilibili_automation_cards", 1)[1].split("def render_bilibili_automation", 1)[0],
    ):
        assert "_render_video_download_control(" in card


# ---------------------------------------------------------------------------
# 5. Sanitizador no caminho Remotion
# ---------------------------------------------------------------------------


def test_remotion_route_sanitizes_the_blueprint():
    block = WORKER.split("def _run_remotion_blueprint(", 1)[1].split("\ndef ", 1)[0]
    assert "sanitize_blueprint_for_prompt(load_blueprint(blueprint_id))" in block
    assert "from .blueprint_length_guard import sanitize_blueprint_for_prompt" in block
    # o sanitizador preserva os placeholders: a substituição continua inteira
    assert "render_blueprint_prompt(blueprint, values)" in block
    assert "find_placeholders(blueprint)" in block


def test_remotion_blueprints_really_have_no_length_keys_leaking():
    """Prova funcional: um blueprint de composição com regras de caracteres
    sai limpo pelo mesmo caminho que a rota Remotion usa."""
    from hermes_ui.blueprint_length_guard import sanitize_blueprint_for_prompt

    cru = {
        "composition_id": "Quiz",
        "constraints": ["nunca inventar factos"],
        "metadata": {
            "character_length_requirement": "STRICTLY 7,000–9,000 characters",
            "strict_character_range": [7000, 9000],
        },
        "output_length_requirement": "STRICTLY between 7,000 and 9,000 characters.",
        "hard_fail_condition": "Any FULL SCRIPT under 7,000 characters is invalid.",
        "output_schema": {"topic": {"type": "string"}},
    }
    limpo = sanitize_blueprint_for_prompt(cru)
    assert limpo["composition_id"] == "Quiz"
    assert limpo["constraints"] == ["nunca inventar factos"]
    assert limpo["output_schema"] == {"topic": {"type": "string"}}
    serializado = json.dumps(limpo, ensure_ascii=False)
    for proibida in (
        "character_length", "strict_character_range", "output_length_requirement",
        "hard_fail_condition", "7,000", "9,000",
    ):
        assert proibida not in serializado, proibida


# ---------------------------------------------------------------------------
# 6. Raízes servidas pelo mini-servidor
# ---------------------------------------------------------------------------


def test_local_media_server_serves_the_task_artifacts_root():
    """Sem `storage/artifacts` o player caía no st.video(caminho) — spinner."""
    helper = MAIN.split("def _tb_media_roots(", 1)[1].split("\ndef ", 1)[0]
    assert '"artifacts": STORAGE / "artifacts"' in helper
    assert '"videos": STORAGE / "videos"' in helper
    assert 'roots["mpt"]' in helper


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
