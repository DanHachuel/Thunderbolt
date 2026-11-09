"""Testes do indicador de estado no título dos cards da Automação YouTube (1.0.78)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

# O bloco do card (o título do expander vive em _youtube_task_card_body).
CARD_BLOCK = MAIN_SOURCE.split("def _youtube_task_card_body", 1)[1].split("@st.fragment", 1)[0]
# O bloco do helper de estado.
ICON_BLOCK = MAIN_SOURCE.split("def _video_task_status_icon", 1)[1].split("\ndef ", 1)[0]
# O bloco que desenha o estado DENTRO do card (barra, badge, erro) — nenhum
# dele pode receber o ícone: o ícone é só do título.
_STATE_BLOCK = MAIN_SOURCE.split("def _render_video_task_state", 1)[1].split("\ndef ", 1)[0]


def test_youtube_card_title_gets_the_status_icon():
    """O título do expander do YouTube termina com o ícone do estado."""
    assert 'with st.expander(f"{task_title} · {task_channel}{_video_task_status_icon(task)}", expanded=False):' in CARD_BLOCK
    # e a chamada do helper é a ÚNICA coisa que se junta ao título
    assert 'f"{task_title} · {task_channel}{_video_task_status_icon(task)}"' in CARD_BLOCK


def test_status_icon_helper_returns_check_for_done_and_cross_for_failure():
    """done -> ✅; failed/error -> ❌; o resto -> string vazia."""
    assert 'state = _catalog_task_state(task)' in ICON_BLOCK
    assert 'if state == "done":' in ICON_BLOCK
    assert 'return " ✅"' in ICON_BLOCK
    assert 'if state in {"failed", "error"}:' in ICON_BLOCK
    assert 'return " ❌"' in ICON_BLOCK
    assert 'return ""' in ICON_BLOCK


def test_status_icon_helper_reads_the_catalog_state_not_the_backend():
    """A leitura é a do card (mesma do player) — nenhuma lógica de estado muda."""
    assert "_catalog_task_state(task)" in ICON_BLOCK
    assert "update_task(" not in ICON_BLOCK
    assert "task.get(\"state\")" not in ICON_BLOCK  # não é o estado cru


def test_status_icon_lives_only_in_the_title_not_in_the_card_body():
    """Proibido: ícone dentro do corpo do card (só no título da aba expansível)."""
    assert "st.button(" in CARD_BLOCK  # os botões continuam lá
    assert "st.image(" in CARD_BLOCK  # a thumbnail continua lá
    assert "_render_video_task_state(task)" in CARD_BLOCK  # e a barra/badge de estado
    # O ícone só aparece no título: nenhum widget do corpo o usa.
    widgets = [block for block in (CARD_BLOCK, _STATE_BLOCK)]
    for block in widgets:
        for line in block.splitlines():
            if any(widget in line for widget in ("st.button", "st.image", "st.progress", "st.caption", "st.write", "st.error")):
                assert "_video_task_status_icon" not in line, f"widget ganhou ícone no corpo: {line.strip()}"
    # e o corpo do card continua com o título LIMPO (sem ícone) — só o expander o leva
    assert 'with st.expander(f"{task_title} · {task_channel}{_video_task_status_icon(task)}", expanded=False):' in CARD_BLOCK
    assert CARD_BLOCK.count("_video_task_status_icon") == 1


def test_other_platform_cards_are_untouched():
    """Só a aba Automação YouTube muda — TikTok/Bilibili/música ficam iguais."""
    tiktok_block = MAIN_SOURCE.split("def _render_tiktok_automation_task_list", 1)[1].split("@st.fragment", 1)[0]
    assert 'with st.expander(f"{task_title} · {task_channel}", expanded=False):' in tiktok_block
    music_block = MAIN_SOURCE.split("def _render_music_automation_card", 1)[1].split("def render_music_automation", 1)[0]
    assert 'with st.expander(f"{title} · {channel}", expanded=False):' in music_block
