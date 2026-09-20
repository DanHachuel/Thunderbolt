from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
PROJECT_RULES = Path("/home/ubuntu/projects/youtube-project-53d03c85/Regras Manus.md").read_text(encoding="utf-8")


def test_facebook_automation_keeps_empty_page_selector_and_does_not_return():
    block = MAIN_SOURCE.split("def render_facebook_automation", 1)[1].split("def render_automation", 1)[0]
    assert "Cadastre primeiro uma página" not in block
    assert 'page_options = [""] +' in block
    assert 'key="facebook_automation_target_page"' in block
    assert "return" not in block.split("pages = _facebook_pages_for_automation()", 1)[1].split("with st.expander", 1)[0]


def test_tiktok_automation_does_not_stop_when_destination_list_is_empty():
    block = MAIN_SOURCE.split("def render_tiktok_automation", 1)[1].split("@st.fragment\ndef _render_youtube_automation_cards", 1)[0]
    assert "Cadastre primeiro um canal TikTok." not in block
    assert 'Nenhum canal TikTok seleccionado' in block


def test_upload_target_uses_empty_selectbox_instead_of_disabled_preregistration_gate():
    block = MAIN_SOURCE.split("def render_upload_destination_target", 1)[1].split("def render_upload_conventional", 1)[0]
    assert 'st.selectbox(select_label, [""], format_func=' in block
    assert "disabled=True" not in block
    assert "Cadastre ou liste pelo menos um canal YouTube" not in block


def test_project_rules_forbid_preregistration_gates():
    assert "nunca criar travas de pré-cadastro" in PROJECT_RULES
    assert "lista de destinos estiver vazia" in PROJECT_RULES
