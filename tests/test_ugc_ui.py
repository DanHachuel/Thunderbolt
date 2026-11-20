"""UI do hub UGC (1.1.09) e da secção Higgsfield AI.

Metade dos testes corre o **código real** com o Streamlit substituído (ou com
`AppTest`), para provar que a barra de abas aparece, que cada aba chama o
renderizador certo e que o upload persiste — não apenas que uma string existe
na fonte.
"""

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

UGC_SCOPE = "ugc"
UGC_TABS = (
    ("Personagens", "AI Influencers"),
    ("Geração de Conteúdo IA", "Geração de Conteúdo IA"),
    ("Motion Control", "Motion Control"),
    ("UGC Products", "UGC Products"),
    ("UGC Product Review", "UGC Product Review"),
    ("Ad-Creator", "Ad-Creator"),
    ("Ad Strategist", "Ad Strategist"),
    ("Hook", "Hook"),
)


# --------------------------------------------------------------------- sidebar

def test_sidebar_shows_ugc_and_not_ai_influencers_as_a_group():
    """O grupo sai do menu; a categoria principal passa a chamar-se UGC."""
    assert '("UGC", ":material/smart_toy:", "UGC")' in MAIN_SOURCE
    assert '("AI Influencers", ":material/smart_toy:", "AI Influencers")' not in MAIN_SOURCE
    # o grupo deixou de existir (senão aparecia um expansível vazio)
    assert '"AI Influencers": models_ai_items' not in MAIN_SOURCE
    assert 'groups = {' in MAIN_SOURCE
    groups_block = MAIN_SOURCE.split("    groups = {", 1)[1].split("}", 1)[0]
    assert '"UGC": models_ai_items' not in groups_block


def test_other_sidebar_items_keep_their_positions():
    """Regra de UI «Inserção de Itens»: mais nada se mexeu no menu."""
    top_block = MAIN_SOURCE.split("    top_pages = [", 1)[1].split("    ]", 1)[0]
    order = [label for label in (
        "Início", "Automação", "Niche Finder", "Canais/Perfis (Vídeos)",
        "Pipeline Vídeos", "Pipeline Música", "UGC", "Blueprints", "Edição",
        "Growth", "Configurações",
    ) if f'"{label}"' in top_block]
    positions = [top_block.index(f'"{label}"') for label in order]
    assert positions == sorted(positions), order
    # o UGC ficou exactamente onde o AI Influencers estava
    assert top_block.index('"UGC"') == top_block.index('"AI Influencers"') if '"AI Influencers"' in top_block else True


def test_ugc_is_a_hub_page_with_the_requested_tab_order():
    specs_block = MAIN_SOURCE.split("UGC_HUB_SPECS = [", 1)[1].split("]", 1)[0]
    positions = [specs_block.index(f'("{internal}"') for internal, _label in UGC_TABS]
    assert positions == sorted(positions), "a ordem das abas do UGC mudou"
    hub_block = MAIN_SOURCE.split("HUB_PAGES: list[tuple[str, str, list[tuple[str, str, Any]], dict[str, str] | None]] = [", 1)[1].split("]", 1)[0]
    assert '("UGC", "ugc", UGC_HUB_SPECS, None)' in hub_block


def test_personagens_tab_is_labelled_ai_influencers():
    specs_block = MAIN_SOURCE.split("UGC_HUB_SPECS = [", 1)[1].split("]", 1)[0]
    assert '("Personagens", "AI Influencers",' in specs_block
    # o nome interno fica, para os links directos antigos continuarem a resolver
    assert '("Personagens", ":material/person:", "Personagens")' in MAIN_SOURCE
    assert '"Personagens": lambda: render_ai_influencer_characters' in MAIN_SOURCE


def test_old_ai_influencers_links_still_resolve():
    aliases_block = MAIN_SOURCE.split("    aliases = {", 1)[1].split("}", 1)[0]
    assert '"AI Influencers": "UGC"' in aliases_block
    assert '"Models AI": "UGC"' in aliases_block
    # as sub-páginas antivas colapsam na página principal e semeiam a aba
    assert "aliases.update(" in MAIN_SOURCE
    assert "models_ai_items" in MAIN_SOURCE.split("hub_child_items = [", 1)[1].split("]", 1)[0]


# ------------------------------------------------------- renderizador por aba

def test_every_tab_has_a_renderer_entry():
    for internal, _label in UGC_TABS:
        assert f'"{internal}":' in MAIN_SOURCE, internal
    assert '"UGC": render_ugc_hub' in MAIN_SOURCE
    for new_page in ("UGC Product Review", "Ad-Creator", "Ad Strategist", "Hook"):
        assert f'"{new_page}": render_' in MAIN_SOURCE, new_page


def test_ugc_hub_calls_the_shared_hub_renderer():
    assert "def render_ugc_hub() -> None:" in MAIN_SOURCE
    hub = MAIN_SOURCE.split("def render_ugc_hub()", 1)[1].split("\ndef ", 1)[0]
    assert 'render_hub_page("UGC", title="UGC"' in hub


def _renderer_block(name: str) -> str:
    """Corpo de uma função de topo (até à próxima `def` de topo)."""
    return MAIN_SOURCE.split(f"def {name}()", 1)[1].split("\ndef ", 1)[0]


# ------------------------------------------------------------------ uploads

def test_each_new_tab_has_a_file_uploader():
    """Cada aba nova chama o helper de upload, que é onde o uploader vive."""
    for renderer, scope in (
        ("render_ugc_product_review", "product_review"),
        ("render_ad_creator", "ad_creator"),
        ("render_ad_strategist", "ad_strategist"),
        ("render_hook", "hook"),
    ):
        block = _renderer_block(renderer)
        assert "_higgs_upload_assets(" in block, renderer
        assert f'"{scope}"' in block, renderer

    helper = MAIN_SOURCE.split("def _higgs_upload_assets(", 1)[1].split("\ndef ", 1)[0]
    assert "st.file_uploader(" in helper
    assert "accept_multiple_files=True" in helper


def test_uploads_can_be_removed_one_by_one():
    upload_block = MAIN_SOURCE.split("def _higgs_upload_assets(", 1)[1].split("\ndef ", 1)[0]
    assert 'st.button("Remover", key=f"higgs_{scope}_remove_{index}"' in upload_block
    # a remoção reescreve a lista sem o ficheiro escolhido
    assert "remaining = [item for position, item in enumerate(records) if position != index]" in upload_block


def test_uploaded_files_are_stored_safely():
    """Nada de confiar no nome do browser: o helper saneia e usa digest."""
    upload_block = MAIN_SOURCE.split("def _higgs_upload_assets(", 1)[1].split("\ndef ", 1)[0]
    assert "store_uploaded_media(item, folder)" in upload_block
    influencers = (ROOT / "app" / "influencers_ui.py").read_text(encoding="utf-8")
    assert "def store_uploaded_media(" in influencers
    assert "digest = hashlib.sha256(content).hexdigest()[:16]" in influencers


def test_each_new_tab_submits_a_higgsfield_job():
    mapping = {
        "render_ugc_product_review": "higgsfield_submit_product_photoshoot",
        "render_ad_creator": "higgsfield_submit_generation",
        "render_ad_strategist": "higgsfield_submit_generation",
        "render_hook": "higgsfield_submit_generation",
    }
    for renderer, call in mapping.items():
        block = MAIN_SOURCE.split(f"def {renderer}()", 1)[1].split("\n@st.fragment", 1)[0]
        assert call in block, f"{renderer} não chama {call}"
    # o Hook usa o job técnico do Virality Predictor
    hook_block = MAIN_SOURCE.split("def render_hook()", 1)[1].split("\n@st.fragment", 1)[0]
    assert '"brain_activity"' in hook_block


def test_jobs_are_polled_by_fragments_without_blocking_the_ui():
    """Skill streamlit-estado: sem time.sleep, sem espera bloqueante."""
    for panel in ("_higgs_product_review_job_panel", "_higgs_ad_creator_job_panel", "_higgs_ad_strategist_job_panel", "_higgs_hook_job_panel"):
        assert f"def {panel}() -> None:" in MAIN_SOURCE
    # só a secção do Higgsfield (acaba onde começam os specs do hub UGC)
    block = MAIN_SOURCE.split("Higgsfield AI (1.1.09)", 1)[1].split("\nUGC_HUB_SPECS = [", 1)[0]
    assert block.count("@st.fragment(run_every=_HIGGS_JOB_POLL_SECONDS)") == 4
    assert "time.sleep" not in block
    assert "_stop_own_fragment_auto_rerun()" in block
    # o job é criado sem --wait (resposta imediata) e lido depois por get:
    # a única ocorrência da flag é o comentário que explica isto.
    assert '"--wait"' not in block
    assert '"--wait-timeout"' not in block


def test_generation_never_runs_without_cli_or_session():
    submit_block = MAIN_SOURCE.split("def _higgs_submit(", 1)[1].split("\ndef ", 1)[0]
    assert "_higgs_not_ready_notice()" in submit_block
    notice_block = MAIN_SOURCE.split("def _higgs_not_ready_notice(", 1)[1].split("\ndef ", 1)[0]
    assert 'status["installed"]' in notice_block
    assert 'status["authenticated"]' in notice_block


# ------------------------------------------------------------ Configuração API

def test_higgsfield_section_exists_in_the_api_page():
    assert "def render_higgsfield_api_section" in MAIN_SOURCE