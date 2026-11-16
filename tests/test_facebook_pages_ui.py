from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_youtube_channel_country_is_editable_and_visible_on_card():
    assert 'edited_country = st.selectbox("País"' in MAIN_SOURCE
    assert 'manual_country = st.selectbox("País"' in MAIN_SOURCE
    assert 'import_country = st.selectbox("País"' in MAIN_SOURCE
    assert 'f"**{channel.get(\'name\', \'Sem nome\')}**{f\' · {country_label}\' if country_label else \'\'}"' in MAIN_SOURCE


def test_facebook_pages_are_public_url_only_and_use_channel_cards():
    assert "def render_facebook_pages():" in MAIN_SOURCE
    assert 'st.title("Facebook Pages")' in MAIN_SOURCE
    assert 'st.text_input("URL pública da página"' in MAIN_SOURCE
    assert '"platform": "facebook"' in MAIN_SOURCE
    assert 'with st.container(border=True):' in MAIN_SOURCE[MAIN_SOURCE.index("def render_facebook_pages"):MAIN_SOURCE.index("def render_channels")]
    assert '"Facebook Pages": render_facebook_pages' in MAIN_SOURCE


def test_social_pages_are_under_video_profiles_and_automation_placeholders_exist():
    channel_block = MAIN_SOURCE.split("    channel_profile_items = [", 1)[1].split("    ]", 1)[0]
    assert channel_block.index('("Canais Tiktok",') < channel_block.index('("Contas Instagram",') < channel_block.index('("Facebook Pages",')
    # Commit c3a5909 ("feat: separar abas das automacoes de tiktok musica e
    # bilibili") substituiu os placeholders "lambda: None" das automações
    # Musicas e Bilibili por renderers reais; UGC e Influencer Content seguem
    # reservados.
    # 1.1.02 — essas plataformas passaram a ser abas da página «Automação»
    # (botões coloridos em render_automation_hub); os renderizadores são os
    # mesmos e UGC/Influencer deixaram de ser páginas em branco.
    hub = MAIN_SOURCE.split("def render_automation_hub(", 1)[1].split("\ndef main():", 1)[0]
    real_renderers = ("facebook", "musicas", "bilibili")
    for tab in real_renderers:
        assert f'active_tab == "{tab}":' in hub
    for tab in ("ugc", "influencer"):
        assert f'active_tab == "{tab}":' in hub
        assert 'render_edit_placeholder(' in hub
    assert "render_facebook_automation()" in hub
    assert "render_music_automation()" in hub
    assert "render_bilibili_automation()" in hub
    assert "automation_items = []" in MAIN_SOURCE
