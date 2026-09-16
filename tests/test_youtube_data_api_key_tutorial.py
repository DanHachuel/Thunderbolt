from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_youtube_data_api_key_tutorial_is_registered_in_documentation_menu():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    label = "YouTube Data API Key (Public Data)"
    assert f'("{label}", ":material/vpn_key:", "{label}")' in source
    assert f'"{label}": "/documentacao/tutoriais/youtube-data-api-key"' in source
    assert f'"{label}": render_youtube_data_api_key_tutorial' in source


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
