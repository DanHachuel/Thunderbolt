from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_google_oauth_tutorial_is_registered_in_documentation_menu():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert '("OAuth do Google", ":material/key:", "OAuth do Google")' in source
    assert '"OAuth do Google": "/documentacao/tutoriais/oauth-google"' in source
    assert '"OAuth do Google": render_google_oauth_tutorial' in source


def test_google_oauth_tutorial_contains_required_setup_sections_and_safe_secret_guidance():
    tutorial = (ROOT / "seed" / "references" / "tutorial-oauth-google.md").read_text(encoding="utf-8")

    for heading in (
        "Pré-requisitos",
        "Passo 1 — Aceder ao Google Cloud Console",
        "Passo 3 — Activar a YouTube Data API v3",
        "Passo 4 — Configurar a tela de consentimento OAuth",
        "Passo 5 — Adicionar utilizadores de teste",
        "Passo 6 — Criar as credenciais OAuth",
        "Passo 7 — Configurar o Thunderbolt",
        "Passo 8 — Testar a autenticação",
        "Solução de problemas",
        "Escopos importantes para o YouTube",
    ):
        assert heading in tutorial

    assert "Aplicativo para computador" in tutorial
    assert "Desktop app" in tutorial
    assert "Configurações → Configuração API → API Keys Upload → Contas Google" in tutorial
    assert "Nunca partilhe o Client Secret" in tutorial
    assert "redirect_uri_mismatch" in tutorial
    assert "youtube.upload" in tutorial
