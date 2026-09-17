from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
PACKAGE_SOURCE = (ROOT / "package.json").read_text(encoding="utf-8")
THEME_CONFIG = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")


def test_streamlit_theme_config_defaults_to_dark_with_moneyprinter_style_semantics():
    assert "[theme]" in THEME_CONFIG
    assert "[theme.dark]" in THEME_CONFIG
    assert 'primaryColor = "#35A7FF"' in THEME_CONFIG
    assert 'backgroundColor = "#0B1118"' in THEME_CONFIG
    assert 'secondaryBackgroundColor = "#121B26"' in THEME_CONFIG
    assert 'textColor = "#F4F8FB"' in THEME_CONFIG
    assert '[client]\ntoolbarMode = "auto"' in THEME_CONFIG


def test_package_distributes_streamlit_theme_config_and_new_release_version():
    assert '"version": "0.8.58"' in PACKAGE_SOURCE
    assert '".streamlit/config.toml"' in PACKAGE_SOURCE


def test_native_streamlit_theme_menu_is_preserved_without_internal_theme_selector():
    assert 'render_ui_language_picker(ui_language)' in MAIN_SOURCE
    assert 'render_ui_theme_picker' not in MAIN_SOURCE
    assert 'top_ui_theme_selector' not in MAIN_SOURCE
    assert 'theme_col' not in MAIN_SOURCE
    assert 'stAppDeployButton' not in MAIN_SOURCE
    assert 'stMainMenu' not in MAIN_SOURCE


def test_custom_css_inherits_active_streamlit_theme_instead_of_forcing_dark_palette():
    css_start = MAIN_SOURCE.index("st.markdown(\"\"\"\n<style>")
    css_end = MAIN_SOURCE.index('</style>\n\"\"\", unsafe_allow_html=True)', css_start)
    css = MAIN_SOURCE[css_start:css_end]

    assert "background:transparent" in css
    assert "color:inherit" in css
    assert "currentColor" in css
    assert "color-mix(in srgb" in css
    for forced_dark_rule in (
        "background:#091018",
        "background:#101b25",
        "background:rgba(18,27,38,.92)",
        "color:#e7edf2",
        "color:#f4f8fb",
        "color:#9cafbf",
    ):
        assert forced_dark_rule not in css


def test_native_theme_detector_applies_flat_light_background_and_removes_it_in_dark():
    assert 'theme_base = (st.get_option("theme.base") or "dark").lower()' in MAIN_SOURCE
    assert 'stActiveTheme-/-v2' in MAIN_SOURCE
    assert 'selected === "Light"' in MAIN_SOURCE
    assert 'selected === "Dark"' in MAIN_SOURCE
    assert 'STYLE_ID = "thunderbolt-light-theme-style"' in MAIN_SOURCE
    assert "--primary-bg-color" in MAIN_SOURCE
    assert "#7A6FE4" in MAIN_SOURCE
    assert '[data-testid="stSidebar"]' in MAIN_SOURCE
    assert "background-image: none !important" in MAIN_SOURCE
    assert "thunderbolt-prismatic-gradient" not in MAIN_SOURCE
    assert "MutationObserver" not in MAIN_SOURCE
    assert 'theme_base = (st.get_option("theme.base") or "dark").lower()' in MAIN_SOURCE
    assert 'st.get_option("theme.base") == "dark"' not in MAIN_SOURCE


def test_theme_labels_are_available_for_all_supported_languages():
    from hermes_ui.languages import LANGUAGE_CODES, UI_TRANSLATIONS

    for code in LANGUAGE_CODES:
        assert UI_TRANSLATIONS[code]["Theme"]
        assert UI_TRANSLATIONS[code]["Dark"]
        assert UI_TRANSLATIONS[code]["Light"]


def test_theme_fix_keeps_native_streamlit_toolbar_and_platform_chip_identity_colors():
    assert "stAppDeployButton" not in MAIN_SOURCE
    assert "stMainMenu" not in MAIN_SOURCE
    assert "stToolbar" not in MAIN_SOURCE
    assert '[data-testid="stMultiSelectTagsContainer"] span[data-tag][aria-label="YouTube"] { background:#ff0000 !important; }' in MAIN_SOURCE
    assert '[data-testid="stMultiSelectTagsContainer"] span[data-tag][aria-label="TikTok"] { background:#000000 !important; }' in MAIN_SOURCE


def test_growth_labels_have_translation_entries():
    source = Path(__file__).parents[1].joinpath("hermes_ui", "languages.py").read_text(encoding="utf-8")
    assert source.count('"Analista Facebook Pages"') >= 10
    assert source.count('"Analista Bilibili"') >= 10


def test_theme_bootstrap_uses_native_streamlit_iframe():
    assert "_THEME_BOOTSTRAP =" in MAIN_SOURCE
    assert 'if hasattr(st, "html")' in MAIN_SOURCE
    assert "st.html(_THEME_BOOTSTRAP" in MAIN_SOURCE
    assert "components.html(_THEME_BOOTSTRAP, height=0, width=0)" in MAIN_SOURCE
    assert "st.iframe(" not in MAIN_SOURCE
    assert "srcdoc=" not in MAIN_SOURCE
