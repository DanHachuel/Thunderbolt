from __future__ import annotations

import json
from pathlib import Path


MAIN_SOURCE = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")


def test_innertube_key_has_a_safe_api_test_control():
    block = MAIN_SOURCE.split('with st.form("innertube_api_key_form"):', 1)[1].split('if save_innertube_api_key:', 1)[0]

    assert 'test_innertube_api_key(innertube_api_key_value)' in block
    assert 'widget_key="api_test_innertube"' in block
    assert '_render_api_test_control(' in block


def test_kaggle_and_apify_keep_api_test_controls_in_their_configuration_cards():
    settings = MAIN_SOURCE.split("def render_settings():", 1)[1].split("def render_google_accounts():", 1)[0]
    niche = settings.split("def render_niche_finder_fragment():", 1)[1].split('with st.expander("Niche Finder", expanded=False):', 1)[0]

    assert 'st.tabs(["Kaggle", "Apify", "Kalodata"])' in niche
    assert 'test_kaggle_credentials(kaggle_username, kaggle_api_key, kaggle_kernel_slug)' in niche
    assert 'widget_key="api_test_kaggle"' in niche
    assert 'test_apify_credentials(apify_api_token)' in niche
    assert 'widget_key="api_test_apify"' in niche
    assert 'test_kalodata_credentials(kalodata_api_key, kalodata_base_url)' in niche
    assert 'widget_key="api_test_kalodata"' in niche
    assert '"kalodata_api_key": kalodata_api_key.strip()' in settings
    assert '"kalodata_base_url": kalodata_base_url.strip()' in settings
    assert 'key="save_niche_kaggle"' in niche
    assert 'key="save_niche_apify"' in niche
    assert 'key="save_niche_kalodata"' in niche
    assert '@st.fragment\n                def render_niche_finder_fragment():' in settings
    assert 'with st.expander("Niche Finder", expanded=False):' in settings
    assert 'render_niche_finder_fragment()' in settings
    assert 'st.success("Configuração Kaggle guardada.")' in niche
    assert 'st.success("Configuração Apify guardada.")' in niche
    assert 'st.success("Configuração Kalodata guardada.")' in niche
    assert "niche_finder_save_notice" not in settings
    assert "st.rerun()" not in niche


def test_kaggle_diagnostic_shows_safe_message_and_uses_public_kernel_default():
    storage_source = (Path(__file__).resolve().parents[1] / "hermes_ui" / "storage.py").read_text(encoding="utf-8")
    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    metadata_path = Path(__file__).resolve().parents[1] / "app" / "modules" / "niche_finder" / "kaggle_kernel" / "kernel-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert 'detail = str(current.get("message") or "").strip() if test_key == "kaggle" else ""' in MAIN_SOURCE
    assert 'if detail:' in MAIN_SOURCE
    assert '"kaggle_kernel_slug": "thunderbolt"' in storage_source
    assert metadata["id"] == "danhachuel/thunderbolt"
    assert metadata["is_private"] is False
    assert "kaggle>=1.6.17,<3" in requirements
    assert "kagglehub>=0.3,<1" in requirements
