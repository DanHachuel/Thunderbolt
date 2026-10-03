from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


# test_global_notification_toast_runs_outside_notifications_page foi removido
# de propósito: o commit 9fb03dc ("fix: remover reconciliacao global no arranque
# das paginas", 2026-09-17, pré-0.9.32) retirou deliberadamente a chamada
# `render_global_notification_toasts()` de main(), desligando o toast global no
# arranque das páginas (a reconciliação passou a ser manual, pelo botão
# "Actualizar notificações"). Verificar essa ligação seria verificar um
# comportamento removido; os testes restantes cobrem propriedades que
# continuam reais (CSS do toast e não-marcacão de lidas no ciclo).


def test_global_notification_toast_is_positioned_at_bottom_right():
    css_start = MAIN_SOURCE.index("/* Notificações globais:")
    css_end = MAIN_SOURCE.index("</style>", css_start)
    css = MAIN_SOURCE[css_start:css_end]

    assert '[data-testid="stToastContainer"]' in css
    assert "bottom:1rem" in css
    assert "right:1rem" in css
    assert "top:auto" in css
    assert "z-index:100000" in css


def test_notification_toast_keeps_history_read_state_unchanged():
    cycle_start = MAIN_SOURCE.index("def _render_notification_toast_cycle()")
    cycle_end = MAIN_SOURCE.index("def localized_tab_labels", cycle_start)
    cycle_source = MAIN_SOURCE[cycle_start:cycle_end]

    assert "mark_notification_read" not in cycle_source
    assert "mark_all_notifications_read" not in cycle_source
    assert "unread_only=True" in cycle_source
