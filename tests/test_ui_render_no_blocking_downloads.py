"""1.0.84 — regressão de performance: a página não pode ler vídeos para renderizar.

RELATO: depois do runtime permanente (1.0.81), a interface deixava de carregar
(loading infinito no F5), as thumbnails apareciam como caixas cinzas e os
downloads de vídeo/roteiro só arrancavam depois de o utilizador carregar em
"Parar Carregamento" no navegador.

CAUSA RAIZ (medida nesta máquina): os `st.download_button` de vídeo passavam o
STREAM do ficheiro, e o Streamlit lê o stream INTEIRO durante a renderização
para montar o payload de download. Com 24 vídeos de 40-123 MB (2,18 GB no
total; 493 MB só na primeira página) cada rerun lia tudo outra vez — 950 MB de
leituras de disco numa sessão curta. O run do script nunca terminava, os
`/media/` das thumbnails ficavam pendentes atrás dele e o download só arrancava
quando o abort do run libertava o servidor.

FIX: downloads alimentados SÓ A PEDIDO (o padrão «Preparar downloads» que a
invariante 0.9.95 do repo já exige) + `_file_bytes` cacheado sem spinner.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

CARD_BLOCK = MAIN.split("def _youtube_task_card_body", 1)[1].split("@st.fragment", 1)[0]
PIPELINE_BLOCK = MAIN.split("def _render_youtube_automation_cards", 1)[1].split("\ndef ", 1)[0]


def test_video_download_is_lazy_not_read_on_every_render():
    """O stream do vídeo só é aberto DEPOIS do clique em «Preparar»."""
    assert "video_path.open(\"rb\")" in CARD_BLOCK
    assert 'prepare_key = f"automation_prepare_video_{task_id}"' in CARD_BLOCK
    assert "if not st.session_state.get(prepare_key):" in CARD_BLOCK
    assert "st.session_state[prepare_key] = True" in CARD_BLOCK
    assert 'key=f"automation_prepare_video_button_{task_id}"' in CARD_BLOCK


def test_prepare_button_tells_the_user_why():
    """O botão explica que o ficheiro é grande e só é lido a pedido."""
    assert "Preparar Vídeo para download" in CARD_BLOCK
    assert "100 MB" in CARD_BLOCK


def test_missing_video_keeps_the_button_disabled():
    """Sem ficheiro não se tenta ler nada: botão desabilitado (nunca erro)."""
    assert 'data=b""' in CARD_BLOCK
    assert 'file_name="video.mp4"' in CARD_BLOCK
    assert CARD_BLOCK.count("disabled=True") >= 1


def test_pipeline_card_download_is_lazy_too():
    """O card do Backlog/Pipeline tem o mesmo tratamento (era o outro leitor)."""
    assert "video_file.open(\"rb\")" in MAIN
    assert 'prepare_key = f"pipeline_prepare_video_{task[\'id\']}"' in MAIN
    assert 'key=f"pipeline_prepare_video_button_{task[\'id\']}"' in MAIN


def test_file_bytes_helper_is_cached_without_spinner():
    """`_file_bytes` passa pelo cache sem spinner — não bloqueia a página."""
    assert "@st.cache_data(show_spinner=False, max_entries=256)" in MAIN
    assert "def _cached_file_bytes(" in MAIN
    assert "def _file_bytes(path: Path | None) -> bytes:" in MAIN
    helper = MAIN.split("def _file_bytes(", 1)[1].split("\ndef ", 1)[0]
    assert "return b\"\"" in helper  # ficheiro ausente: nunca rebenta


def test_thumbnail_path_tries_the_legacy_locations():
    """Caminhos legados (relativos de antes do STORAGE absoluto) continuam a resolver."""
    helper = MAIN.split("def _task_thumbnail_path(", 1)[1].split("\ndef ", 1)[0]
    assert 'THUNDERBOLT_HOME' in helper
    assert 'thunderbolt_home / raw' in helper
    assert 'thunderbolt_home / "storage" / raw' in helper
    assert "path.is_file()" in helper


def test_thumbnail_render_never_raises_on_a_bad_path():
    """`is_file()` dentro de try/except: caminho inacessível dá placeholder."""
    helper = MAIN.split("def _render_task_thumbnail(", 1)[1].split("\ndef ", 1)[0]
    assert "try:" in helper
    assert "except OSError:" in helper
    assert "Thumbnail não gerada" in helper


def test_no_unprotected_stream_read_in_the_youtube_card():
    """Nenhum `open()` de vídeo fora do ramo «preparado» (só o comentário explica)."""
    for line in CARD_BLOCK.splitlines():
        if "video_path.open(" in line:
            # a única ocorrência permitida é o `with` real, recuado 24+ espaços
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # comentário que documenta a regressão
            assert line.startswith(" " * 24), f"leitura de vídeo fora do ramo preparado: {stripped}"


@pytest.mark.parametrize("function", ["_file_bytes", "_cached_file_bytes"])
def test_helpers_are_valid_python(function):
    tree = ast.parse(MAIN)
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert function in names


def test_invariant_comment_still_documents_the_lazy_download_rule():
    """A invariante 0.9.95 continua escrita (regra anti-pré-carregamento)."""
    assert "Downloads SEMPRE via st.download_button alimentado só a pedido" in MAIN
    assert "nunca pré-carregar roteiros/thumbnails/vídeos" in MAIN
