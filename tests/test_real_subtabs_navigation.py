from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_growth_is_a_page_with_real_content_tabs():
    assert '"Growth": growth_items' in MAIN_SOURCE
    assert 'growth_items = []' in MAIN_SOURCE
    assert 'growth_tabs = render_localized_tabs([' in MAIN_SOURCE
    assert 'with growth_tabs[0]:' in MAIN_SOURCE
    assert '"Growth Youtube", "Growth Tiktok", "Growth Instagram", "Facebook Pages", "Growth Bilibili"' in MAIN_SOURCE.replace("\n", " ")


def test_documentation_is_a_page_with_real_content_tabs():
    assert '"Documentação": documentation_items' in MAIN_SOURCE
    assert 'documentation_items = []' in MAIN_SOURCE
    assert 'documentation_tabs = render_localized_tabs([' in MAIN_SOURCE
    assert 'with documentation_tabs[0]:' in MAIN_SOURCE
    assert '"Meta", "Supabase", "Kaggle", "Apify", "YouTube Video-Upload Frontend",' in MAIN_SOURCE.replace("\n", " ")


def test_growth_and_documentation_do_not_use_expandable_submenus():
    growth_block = MAIN_SOURCE.split('    growth_items = [', 1)[1].split('    settings_items = [', 1)[0]
    documentation_block = MAIN_SOURCE.split('    documentation_items = [', 1)[1].split('    settings_items = [', 1)[0]
    assert 'with st.expander' not in growth_block
    assert 'with st.expander' not in documentation_block
    assert 'Seleccione um tutorial no menu expansível' not in MAIN_SOURCE
    assert 'Seleccione uma das abas de Growth no menu expansível' not in MAIN_SOURCE


def test_subtab_renderers_are_wired():
    assert '"Growth": render_growth_pages' in MAIN_SOURCE
    assert '"Analise Growth": render_growth_pages' in MAIN_SOURCE
    assert '"Documentação": render_documentation_pages' in MAIN_SOURCE
    assert '"Tutoriais": render_documentation_pages' in MAIN_SOURCE


def test_existing_upload_music_reference_remains_tab_based():
    assert 'render_localized_tabs(["JewelMusic", "Pushtunes", "ytmusicapi", "DistroKid"])' in MAIN_SOURCE
