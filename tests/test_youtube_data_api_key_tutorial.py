from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_youtube_data_api_key_tutorial_is_registered_in_documentation_menu():
    # 1.0.52 — os tutoriais saíram do menu lateral e vivem como aba interna
    # das Configurações; o tutorial continua registado nessa aba.
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    label = "YouTube Data API Key (Public Data)"
    assert "with documentation_tab:" in source
    assert f'"{label}",' in source.replace("\n", " ")
    assert "render_youtube_data_api_key_tutorial," in source
    # nada de item de menu lateral nem rota /documentacao para o tutorial
    assert f'("{label}", ":material/vpn_key:", "{label}")' not in source
    assert '"/documentacao/tutoriais/youtube-data-api-key"' not in source


def test_youtube_data_api_key_tutorial_covers_public_data_setup_and_security():
    tutorial = (ROOT / "seed" / "references" / "tutorial-youtube-data-api-key.md").read_text(encoding="utf-8")
    for expected in (
        "YouTube Data API v3",
        "Chave de API",
        "INNERTUBE_API_KEY",
        "Restringir a chave",
        "quotaExceeded",
        "API_KEY_INVALID",
        "OAuth 2.0",
        "Nunca publique a API Key",
    ):
        assert expected in tutorial
    assert "# Tutorial YouTube Data API Key (Public Data)" not in tutorial
    assert "Google Drive" not in tutorial
    assert "drive.google.com" not in tutorial
    assert len(tutorial) > 3000
