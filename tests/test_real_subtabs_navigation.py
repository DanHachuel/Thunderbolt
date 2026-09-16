from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_growth_is_a_page_with_real_content_tabs():
    assert '"Growth": growth_items' in MAIN_SOURCE
    assert 'growth_items = growth_analysis_items' in MAIN_SOURCE
    assert '"Growth Youtube": render_growth_youtube' in MAIN_SOURCE
    assert '"Growth Tiktok": render_growth_tiktok' in MAIN_SOURCE
    assert '"Growth Youtube", "Growth Tiktok", "Growth Instagram", "Facebook Pages", "Growth Bilibili"' in MAIN_SOURCE.replace("\n", " ")


def test_documentation_is_a_page_with_real_content_tabs():
    assert '"Documentação": documentation_items' in MAIN_SOURCE
    assert 'documentation_items = tutorial_items' in MAIN_SOURCE
    assert '"Meta": render_models_ai_tutorial' in MAIN_SOURCE
    assert '"Supabase": render_supabase_tutorial' in MAIN_SOURCE
    assert '"Meta", "Supabase", "Kaggle", "Apify", "YouTube Video-Upload Frontend",' in MAIN_SOURCE.replace("\n", " ")


def test_growth_and_documentation_do_not_use_expandable_submenus():
    assert 'growth_items = []' not in MAIN_SOURCE
    assert 'documentation_items = []' not in MAIN_SOURCE
    assert 'Seleccione um tutorial no menu expansível' not in MAIN_SOURCE
    assert 'Seleccione uma das abas de Growth no menu expansível' not in MAIN_SOURCE


def test_subtab_renderers_are_wired():
    assert '"Growth Youtube": render_growth_youtube' in MAIN_SOURCE
    assert '"Growth Tiktok": render_growth_tiktok' in MAIN_SOURCE
    assert '"Growth Instagram": render_growth_instagram' in MAIN_SOURCE
    assert '"Facebook Pages": render_growth_facebook_pages' in MAIN_SOURCE
    assert '"Growth Bilibili": render_growth_bilibili' in MAIN_SOURCE
    assert '"Meta": render_models_ai_tutorial' in MAIN_SOURCE
    assert '"Supabase": render_supabase_tutorial' in MAIN_SOURCE


def test_existing_upload_music_reference_remains_tab_based():
    assert 'render_localized_tabs(["JewelMusic", "Pushtunes", "ytmusicapi", "DistroKid"])' in MAIN_SOURCE
