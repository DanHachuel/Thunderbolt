import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_ui.creative_generation import CreativeGenerationError, generate_video_keywords
from hermes_ui.languages import ui_text


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
PIPELINE_SOURCE = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")
LANGUAGES_SOURCE = (ROOT / "hermes_ui" / "languages.py").read_text(encoding="utf-8")


class VideoCreationAITests(unittest.TestCase):
    def test_video_creation_has_one_subject_and_one_combined_generation_button(self):
        self.assertNotIn('"Tópico ou briefing"', MAIN_SOURCE)
        self.assertIn('"Video Subject"', MAIN_SOURCE)
        self.assertIn('key=f"{prefix}_generate_video_content"', MAIN_SOURCE)
        self.assertIn('on_click=generate_content_callback', MAIN_SOURCE)
        self.assertIn('generate_video_content_for_ui(', MAIN_SOURCE)
        self.assertIn('st.session_state[f"{prefix}_video_script"] = result["script"]', MAIN_SOURCE)
        self.assertIn('st.session_state[f"{prefix}_video_keywords"] = ", ".join(result["keywords"])', MAIN_SOURCE)
        self.assertIn('topic_value = str(generation_settings.get("video_subject") or "").strip()', MAIN_SOURCE)
        self.assertIn('"Salvar rascunho"', MAIN_SOURCE)
        self.assertIn('if save_draft_callback is not None:', MAIN_SOURCE)
        self.assertIn('def generate_thumbnail_for_ui(', MAIN_SOURCE)
        self.assertIn('def generate_thumbnail_variants_for_ui(', MAIN_SOURCE)
        self.assertIn('generate_thumbnail_prompt(', MAIN_SOURCE)
        self.assertNotIn('Gerar títulos e thumbnails com IA', MAIN_SOURCE)

    def test_video_subject_is_used_before_ai_topic_generation(self):
        resolver = MAIN_SOURCE.split("def resolve_video_subject_for_generation(", 1)[1].split("def generate_video_content_for_ui", 1)[0]
        generator = MAIN_SOURCE.split("def generate_video_content_for_ui(", 1)[1].split("def _generate_video_content_callback", 1)[0]
        self.assertIn('manual_subject = str(entered_subject or "").strip()', resolver)
        self.assertIn('if manual_subject:', resolver)
        self.assertIn('return manual_subject, None', resolver)
        self.assertIn('topic_result = generate_topic_for_channel(settings, channel, selected_blueprint)', resolver)
        self.assertLess(resolver.index("return manual_subject, None"), resolver.index("topic_result = generate_topic_for_channel"))
        self.assertIn('subject, topic_result = resolve_video_subject_for_generation(settings, channel, subject, blueprint)', generator)
        self.assertIn('brief=subject', generator)
        self.assertIn('generate_video_keywords(', generator)

    def test_both_video_creation_pages_use_the_combined_generation_callback(self):
        self.assertIn('"Criação de Vídeos": render_new_video', MAIN_SOURCE)
        self.assertIn('"Criação de Shorts": lambda: render_new_video("Criação de Shorts", "new_shorts"', MAIN_SOURCE)
        self.assertIn('generate_content_callback=lambda: _generate_video_content_callback(', MAIN_SOURCE)

    def test_audio_upload_is_available_and_quantity_control_is_removed(self):
        self.assertNotIn('st.number_input("Quantidade"', MAIN_SOURCE)
        self.assertIn('uploaded_voiceover = st.file_uploader(', MAIN_SOURCE)
        self.assertIn('st.button("Guardar áudio de narração"', MAIN_SOURCE)
        self.assertIn('settings["voiceover_file"]', MAIN_SOURCE)
        self.assertIn('store_voiceover_file(', MAIN_SOURCE)
        self.assertIn('custom-audio-file', PIPELINE_SOURCE)
        self.assertNotIn('Fonteeeee', MAIN_SOURCE)
        self.assertNotIn('Fonteeeee', LANGUAGES_SOURCE)

    def test_scripts_page_reuses_combined_ai_generation_with_selected_blueprint(self):
        self.assertIn('"pipeline_scripts",', MAIN_SOURCE)
        scripts_source = MAIN_SOURCE.split("def render_scripts():", 1)[1].split("@st.cache_data", 1)[0]
        self.assertNotIn('st.text_input("Título", key="script_title"', scripts_source)
        self.assertNotIn('"Tema ou briefing"', scripts_source)
        self.assertIn('title = str(script_settings.get("video_subject") or "").strip()', scripts_source)
        self.assertIn('brief = str(script_settings.get("video_script") or "").strip() or title', scripts_source)
        self.assertIn('generate_content_callback=lambda: _generate_video_content_callback(', MAIN_SOURCE)
        self.assertIn('selected_blueprint,', MAIN_SOURCE)
        self.assertIn('st.session_state["script_draft_keywords"]', MAIN_SOURCE)
        self.assertIn('draft_kind": draft_kind', MAIN_SOURCE)

    def test_channel_voice_is_synchronised_before_audio_selectbox(self):
        self.assertIn('channel_voice = str(channel.get("default_voice") or channel.get("voice") or "").strip()', MAIN_SOURCE)
        self.assertIn('st.session_state[f"{prefix}_voice"] = channel_voice', MAIN_SOURCE)
        self.assertIn('channel_state_key = f"{prefix}_voice_channel_id"', MAIN_SOURCE)
        self.assertIn('channel=selected_one', MAIN_SOURCE)

    def test_channel_language_is_synchronised_before_script_language_selectbox(self):
        self.assertIn('def normalize_video_language(value: Any, default: str = "pt") -> str:', MAIN_SOURCE)
        self.assertIn('def channel_video_language(channel: dict[str, Any] | None, fallback: str = "pt") -> str:', MAIN_SOURCE)
        self.assertIn('channel_language_state_key = f"{prefix}_language_channel_id"', MAIN_SOURCE)
        self.assertIn('channel_language = channel_video_language(channel, fallback=normalized_current_language)', MAIN_SOURCE)
        self.assertIn('st.session_state[f"{prefix}_script_language"] = channel_language', MAIN_SOURCE)
        self.assertIn('settings["script_language"] = st.selectbox(', MAIN_SOURCE)

    def test_selected_channel_summary_includes_configured_video_language(self):
        self.assertIn('video_language = language_label(channel_video_language(channel))', MAIN_SOURCE)
        self.assertIn('**Blueprint utilizado pelo canal:**', MAIN_SOURCE)
        self.assertIn('**Voz:** {voice} · **Idioma:** {video_language}', MAIN_SOURCE)
        self.assertIn('"language": language', MAIN_SOURCE)

    def test_pipeline_generates_video_before_thumbnail_prompt_and_image(self):
        video_position = PIPELINE_SOURCE.index('_update(task_id, stage="video", state="doing", progress=max(52')
        prompt_position = PIPELINE_SOURCE.index('_update(\n        task_id,\n        stage="thumbnail_prompt",\n        state="doing",\n        progress=max(84')
        thumbnail_position = PIPELINE_SOURCE.index('_update(task_id, stage="thumbnail", state="doing", progress=max(86')
        # Commit dde82bb ("feat: add YouTube automation upload controls") mudou o
        # estágio final: a conclusão sem rota de publicação usa o estágio
        # "ready_upload" e o upload "doing" agora corre a progress=100.
        upload_position = PIPELINE_SOURCE.index('_update(task_id, stage="upload", state="doing", progress=100')
        video_artifact_position = PIPELINE_SOURCE.index('artifacts["video"] = str(video_path)')
        self.assertLess(video_position, prompt_position)
        self.assertLess(prompt_position, thumbnail_position)
        self.assertLess(thumbnail_position, upload_position)
        self.assertLess(video_position, video_artifact_position)
        self.assertIn('_update(task_id, stage="ready_upload", state="done", progress=100', PIPELINE_SOURCE)
        self.assertIn('video_ready=True', PIPELINE_SOURCE)
        self.assertIn('o vídeo já está disponível em {video_path}', PIPELINE_SOURCE)

    def test_pipeline_uses_reviewed_script_and_keywords_when_present(self):
        self.assertIn('provided_script = str(generation_settings.get("video_script") or "").strip()', PIPELINE_SOURCE)
        self.assertIn('provided_keywords = generation_settings.get("video_keywords")', PIPELINE_SOURCE)
        self.assertIn('save_script_document(script)', PIPELINE_SOURCE)

    def test_keywords_are_normalised_and_bounded(self):
        with patch(
            "hermes_ui.creative_generation._chat_json",
            return_value={"keywords": ["#AI", "ai", "faceless video", "finance"]},
        ):
            result = generate_video_keywords(
                {},
                {"id": "channel-1", "name": "Brick by Brick Wealth"},
                "How AI changes investing",
                "A script about practical investing and artificial intelligence.",
            )
        self.assertEqual(result, ["AI", "faceless video", "finance"])
        self.assertLessEqual(len(result), 15)

    def test_keywords_require_subject_and_script(self):
        with self.assertRaises(CreativeGenerationError):
            generate_video_keywords({}, {}, "", "script")
        with self.assertRaises(CreativeGenerationError):
            generate_video_keywords({}, {}, "subject", "")

    def test_new_pipeline_labels_are_translated_for_all_supported_languages(self):
        languages = ("pt", "en", "zh", "de", "vi", "tr", "ru", "es", "id", "it")
        for language in languages:
            self.assertTrue(ui_text("Thumbnails", language).strip())
            self.assertTrue(ui_text("Salvar rascunho", language).strip())
            self.assertTrue(ui_text("Refazer thumbnail", language).strip())

    def test_generation_button_is_translated_for_all_supported_languages(self):
        languages = ("pt", "en", "zh", "de", "vi", "tr", "ru", "es", "id", "it")
        source = LANGUAGES_SOURCE.split("VIDEO_GENERATION_TRANSLATIONS", 1)[1]
        for language in languages:
            block = source.split(f'    "{language}": {{', 1)[1].split("    },", 1)[0]
            self.assertIn('Gerar tópico, roteiro e palavras-chave com IA', block)


if __name__ == "__main__":
    unittest.main()
