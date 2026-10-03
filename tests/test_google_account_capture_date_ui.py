from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_google_account_card_renders_and_persists_session_info_capture_date():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    card = source.split("def render_google_accounts(", 1)[1].split("def render_tiktok_api", 1)[0]

    assert 'st.date_input("Data de Captura"' in card
    assert 'key=f"batch_session_info_captured_at_{account_id}"' in card
    assert '"sessionInfoCapturedAt": captured_at_iso' in card
    assert "captured_at=captured_at_iso" in card
