from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_youtube_frontend_upload_tutorial_is_registered_in_documentation_menu():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    # 1.0.56 — a Documentação é sub-item autónomo do menu lateral (grupo
    # «Configurações»); o tutorial é aba do st.tabs dessa página.
    assert '("YouTube Video-Upload Frontend", ":material/video_library:", "YouTube Video-Upload Frontend")' not in source
    assert "def render_documentation_pages" in source
    assert "render_youtube_frontend_upload_tutorial," in source


def test_youtube_frontend_upload_tutorial_keeps_sensitive_session_material_out_of_content():
    tutorial = (ROOT / "seed" / "references" / "youtube-video-upload-frontend.md").read_text(encoding="utf-8")

    assert "Nunca os copie para conversas" in tutorial
    assert "Nunca use valores de exemplo ou chaves encontradas em documentos públicos" in tutorial
    assert "AIz" not in tutorial
    assert "DELEGATED_SESSION_ID" not in tutorial
    assert "metadata_update" not in tutorial
