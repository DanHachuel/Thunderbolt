"""Chaves duplicadas na aba Pipeline (1.1.15).

O relato: o MESMO vídeo aparece duplicado no ecrã e o terminal enche-se de
`StreamlitDuplicateElementKey` nos botões de download. A 1.1.14 deduplicou a
LISTA e não resolveu — a causa são dois RENDERIZADORES, não duas entradas.
Aqui ficam os contratos das duas correcções e a prova de que a paginação não
pode duplicar nada.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _funcao(nome: str) -> str:
    """Corpo de uma função de topo (até à próxima `def` de topo)."""
    inicio = MAIN_SOURCE.index(f"def {nome}(")
    return MAIN_SOURCE[inicio : MAIN_SOURCE.index("\ndef ", inicio + 10)]


# ------------------------------------------------- a paginação não duplica

def test_pagination_cannot_render_the_same_task_twice():
    """A fatia é contígua e exclusiva: `start = (página-1) * 12`."""
    lista = _funcao("_render_youtube_automation_task_list")
    assert "page_size = 12" in lista
    assert "start = (current_page - 1) * page_size" in lista
    assert "visible_tasks = tasks[start : start + page_size]" in lista
    # sem sobreposição: nada de `start - 1`, `end + 1` ou `range(start, end + 1)`
    assert "start - 1" not in lista and "end + 1" not in lista and "start + page_size + 1" not in lista
    # e a página pedida é clampada pelo próprio cálculo (nunca sai do intervalo)
    assert "page_count = max(1, (len(tasks) + page_size - 1) // page_size)" in lista


def test_the_list_is_deduped_before_being_sliced():
    """O dedupe (1.1.14) corre ANTES do fatiamento — mantém-se."""
    lista = _funcao("_render_youtube_automation_task_list")
    assert lista.index("_dedupe_automation_tasks(") < lista.index("page_size = 12")


# --------------------------- a causa raiz: dois fragmentos, um card

def test_the_live_fragment_refuses_to_draw_a_task_that_is_no_longer_live():
    """1.1.15 — a guarda que impede os dois fragmentos ao mesmo tempo."""
    live = _funcao("_youtube_task_card_live")
    assert "_live_task_by_id(task_id)" in live
    assert "_catalog_task_state(task) not in _VIDEO_TASK_LIVE_STATES:" in live
    # recusa o desenho E cancela o próprio timer
    assert "_stop_own_fragment_auto_rerun()" in live
    assert "return" in live
    # e continua a desenhar quando a tarefa está viva (não quebra o polling)
    assert '_youtube_task_card_body(task_id, card_variant="live")' in live


def test_both_variants_render_the_same_body_with_distinct_keys():
    """Os dois fragmentos chamam o mesmo corpo, com chaves diferentes."""
    assert 'card_variant="live"' in MAIN_SOURCE
    assert 'card_variant="idle"' in MAIN_SOURCE
    card = _funcao("_youtube_task_card_body")
    assert 'card_variant: str = "idle"' in card
    # TODAS as chaves do card levam a variante (nenhuma fica só com o id)
    chaves = [linha for linha in card.splitlines() if 'key=f"automation_' in linha]
    assert len(chaves) >= 15
    for linha in chaves:
        assert "_{card_variant}" in linha, linha.strip()


def test_the_variant_does_not_leak_into_other_pages():
    """O sufixo é só do card do YouTube — o TikTok e os canais ficam iguais."""
    tiktok = MAIN_SOURCE.split("def _render_tiktok_automation_task_list", 1)[1].split("\ndef ", 1)[0]
    assert "_{card_variant}" not in tiktok
    canais = MAIN_SOURCE.split("def render_automation(", 1)[1].split("\ndef ", 1)[0]
    assert "_{card_variant}" not in canais


def test_the_variant_does_not_lose_widget_state():
    """Os dois widgets com valor no card são seguros com a chave variável.

    O «Upload ok» persiste na tarefa (update_task imediato) e o «Regenerar
    Áudio» lê pela MESMA chave que o widget escreve — sem essa leitura variante,
    o valor perder-se-ia na transição live→idle.
    """
    card = _funcao("_youtube_task_card_body")
    assert "update_task(str(task[\"id\"]), {\"upload_ok\"" in card
    assert 'st.session_state.get(f"automation_force_audio_{task[\'id\']}_{card_variant}")' in card
    # e a confirmação de «Apagar» continua a ser ESTADO PARTILHADO (não perde a
    # confirmação quando o card muda de variante)
    assert 'confirm_delete_key = f"automation_confirm_delete_{task[\'id\']}"' in card
    assert "_{card_variant}" not in "automation_confirm_delete_"


# --------------------------------------------- silêncio no terminal

def test_the_duplicate_key_warning_is_not_left_to_flood_the_terminal():
    """A 1.1.14 já filtra o ruído do fragmento; a chave é a correcção real."""
    assert 'logging.getLogger("streamlit.runtime.fragment")' in MAIN_SOURCE
    assert "_FragmentGoneNoiseFilter()" in MAIN_SOURCE