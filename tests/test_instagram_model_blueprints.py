from pathlib import Path


MAIN = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
SOCIAL = Path(__file__).parents[1].joinpath("app", "social_networks_ui.py").read_text(encoding="utf-8")


def test_blueprints_group_is_between_ugc_and_editing():
    # 1.1.09 — "AI Influencers" passou a chamar-se "UGC" (mesma posição no menu).
    assert '("Blueprints", ":material/library_books:", "Blueprints")' in MAIN
    assert MAIN.index('("UGC", ":material/smart_toy:", "UGC")') < MAIN.index('("Blueprints", ":material/library_books:", "Blueprints")') < MAIN.index('("Edição", ":material/edit:", "Edição")')
    for label in ("Blueprints Youtube", "Thumbnail Blueprints", "Brandings Youtube", "Prompt-Masters Tiktok", "Facebook Blueprint"):
        assert label in MAIN


def test_instagram_model_selector_has_three_dependent_sources():
    assert 'INSTAGRAM_MODEL_OPTIONS = (' in SOCIAL
    for label in ("Prompt-Masters Tiktok", "Facebook Blueprint", "Personagens Influencer/UGC"):
        assert label in SOCIAL
    assert 'def resolve_instagram_model(' in SOCIAL
    assert 'def _render_instagram_model_selector(' in SOCIAL
    assert 'Modelo/Blueprint' in SOCIAL
    assert 'Guardar modelo atrelado' in SOCIAL


def test_instagram_automation_uses_attached_model_resolver():
    assert 'def render_instagram_automation(' in SOCIAL
    automation = SOCIAL[SOCIAL.index('def render_instagram_automation('):]
    assert 'resolve_instagram_model(profile, settings)' in automation
    assert 'Automação Instagram' in MAIN
    assert 'render_instagram_automation' in MAIN
