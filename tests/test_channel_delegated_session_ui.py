from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_channel_card_renders_and_saves_its_individual_delegated_session_id():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    card = source.split('with st.expander("Upload directo — documento da conta deste canal", expanded=False):', 1)[1].split("render_channel_videos(channel)", 1)[0]

    # Commits 5c6a6ce/a46cb72 ("fix: configure delegated session per channel"): o campo
    # passou a ser atribuído a channel_delegated_session_id dentro do st.form do canal,
    # com uma indentação mais profunda do que quando o teste foi escrito.
    assert 'channel_delegated_session_id = st.text_input(\n                            "DELEGATED_SESSION_ID deste canal"' in card
    assert 'key=f"channel_delegated_session_id_{channel_id}"' in card
    assert '"delegated_session_id": channel_delegated_session_id.strip()' in card
    assert "não é copiado para o documento JSON partilhado" in card


def test_direct_credentials_resolver_prefers_the_channel_specific_value():
    source = (ROOT / "integrations" / "youtube_direct_credentials.py").read_text(encoding="utf-8")
    resolver = source.split("def delegated_session_id", 1)[1].split("def document_status", 1)[0]

    assert 'channel.get("delegated_session_id")' in resolver
    assert "if channel_value:" in resolver
