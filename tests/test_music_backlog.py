from __future__ import annotations

from pathlib import Path


MAIN_SOURCE = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")


def test_music_backlog_is_registered_under_the_music_pipeline_menu():
    music_items = MAIN_SOURCE.split("music_items = [", 1)[1].split("]", 1)[0]

    assert '("Music Backlog", ":material/queue_music:", "Music Backlog")' in music_items
    assert '"Music Backlog": render_music_backlog' in MAIN_SOURCE
    assert '("Vozes Personalizadas", ":material/record_voice_over:", "Vozes Personalizadas")' in music_items
    assert '"Vozes Personalizadas": render_custom_music_voices' in MAIN_SOURCE


def test_custom_music_voices_previews_elevenlabs_personal_voices_without_catalog_or_uploads():
    voices = MAIN_SOURCE.split("def render_custom_music_voices()", 1)[1].split("def render_scripts", 1)[0]

    assert 'st.title("Vozes Personalizadas")' in voices
    # Commit 5b3451f ("feat: integrate ElevenLabs personal voices") substituiu a
    # área reservada vazia pelo Voice Lab do ElevenLabs: as vozes pessoais são
    # listadas apenas para pré-visualização/teste. Mantém-se o intent original
    # de não expor uploads nem catálogo/selecção de vozes nesta área; o input de
    # texto curto serve apenas de amostra para o teste de voz.
    assert "st.file_uploader(" not in voices
    assert "st.selectbox(" not in voices
    assert 'st.text_input("Texto curto para testar uma voz"' in voices
    assert "fetch_personal_voices(settings, force=refresh)" in voices
    assert '"Testar voz"' in voices


def test_music_backlog_accepts_mpeg_audio_from_suno():
    assert '"mpeg"' in MAIN_SOURCE
    music_source = (Path(__file__).resolve().parents[1] / "hermes_ui" / "music.py").read_text(encoding="utf-8")
    assert '".mpeg"' in music_source


def test_music_backlog_combines_created_and_imported_audio_files():
    backlog = MAIN_SOURCE.split("def _music_backlog_records()", 1)[1].split("def _thumbnail_editor_context", 1)[0]

    assert "tasks = list_music_tasks()" in backlog
    assert "for music_file in list_music_files()" in backlog
    assert 'record["source_type"] = "created"' in backlog
    assert '"source_type": "imported"' in backlog
    assert "_render_pipeline_progress_panel()" not in backlog
    assert "load_video_tasks_for_catalog()" not in backlog
    assert "Worker de vídeo" not in backlog


def test_music_backlog_has_upload_download_rename_and_lyrics_controls():
    backlog = MAIN_SOURCE.split("def _render_music_file_card", 1)[1].split("def _thumbnail_editor_context", 1)[0]

    assert 'st.tabs(["Músicas", "Lyrics"])' in backlog
    assert 'st.file_uploader("Adicionar músicas à pasta acima"' in backlog
    assert 'st.file_uploader("Adicionar lyrics"' in backlog
    assert 'st.selectbox("Filtrar por estado"' in backlog
    assert 'run_music_task(record_id' in backlog
    assert 'transition_music_task(record_id, "blocked")' in backlog
    assert '"Descarregar música"' in backlog
    assert '"Descarregar lyrics"' in backlog
    assert '_render_card_pencil(edit_key)' in backlog
    assert '"Música criada"' in backlog
    assert '"Música importada"' in backlog


def test_music_creation_is_audio_only_and_supports_suno_and_lyria():
    creation = MAIN_SOURCE.split("def render_music_creation()", 1)[1].split("def render_custom_music_voices", 1)[0]

    assert 'st.selectbox("Provider de geração musical", ["Suno AI", "Google Lyria", "Eleven Music"]' in creation
    assert '"Idioma da letra/música"' in creation
    assert 'st.selectbox("Género musical", list(MUSIC_GENRES)' in creation
    assert 'st.selectbox("Vocal", list(MUSIC_VOCAL_OPTIONS)' in creation
    assert '"Referências culturais, paisagens, clima ou artistas similares (opcional)"' in creation
    assert 'st.button("Gerar campos musicais com IA"' in creation
    assert 'st.button("Gerar Música"' in creation
    assert creation.index('st.button("Gerar campos musicais com IA"') < creation.index('st.button("Gerar Música"')
    assert creation.index('key="music_task_prompt"') < creation.index('st.button("Gerar campos musicais com IA"')
    assert 'st.session_state["music_task_generated_fields"] = generated' in creation
    assert 'Adicionar ao Music Backlog' not in creation
    assert "MoneyPrinterTurbo" in creation
    assert "render_new_video" not in creation
    assert '"Google Lyria API key"' in MAIN_SOURCE


def test_google_lyria_configuration_has_a_safe_api_test_control():
    settings = MAIN_SOURCE.split('st.markdown("#### Google Lyria — geração musical")', 1)[1].split('with st.expander("Publicação através do Upload-Post"', 1)[0]

    assert 'text_setting("Google Lyria API key", "lyria_api_key", secret=True' in settings
    assert 'st.selectbox("Modelo Google Lyria"' in settings
    assert 'st.form_submit_button("Guardar Google Lyria"' in settings
    assert 'test_voice_provider("google_lyria", {"lyria_api_key": lyria_api_key, "lyria_model": lyria_model})' in settings
    assert 'widget_key="api_test_voice_google_lyria"' in settings


def test_music_lyrics_records_use_existing_markdown_document_storage():
    assert 'document_type") or "").strip() != "music_lyrics"' in MAIN_SOURCE
    assert 'save_script_document({"title": Path(uploaded_lyrics.name).stem, "document_type": "music_lyrics"' in MAIN_SOURCE
    assert 'mime="text/markdown"' in MAIN_SOURCE


def test_thumbnail_cards_offer_download_for_generated_images():
    thumbnails = MAIN_SOURCE.split("def render_thumbnails():", 1)[1].split("def render_automation():", 1)[0]

    assert '"Descarregar thumbnail"' in thumbnails
    assert 'key=f"thumbnail_download_{task_id}_{record[\'variant_index\']}"' in thumbnails


def test_thumbnail_gallery_is_paginated_to_avoid_unbounded_initial_render():
    thumbnails = MAIN_SOURCE.split("def render_thumbnails():", 1)[1].split("def render_automation():", 1)[0]

    assert "page_size = 24" in thumbnails
    assert '"Página de thumbnails"' in thumbnails
    assert "visible_records = records[start : start + page_size]" in thumbnails
