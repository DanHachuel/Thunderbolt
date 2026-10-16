import unittest
from pathlib import Path

from hermes_ui.draft_video import (
    AUDIO_SETTING_KEYS,
    SUBTITLE_SETTING_KEYS,
    VIDEO_SETTING_KEYS,
    missing_content_fields,
    missing_setting_sections,
    normalise_saved_script,
)


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
LANGUAGES_SOURCE = (ROOT / "hermes_ui" / "languages.py").read_text(encoding="utf-8")


class DraftVideoTests(unittest.TestCase):
    def test_normalise_saved_script_reads_markdown_history_and_keywords(self):
        record = {
            "id": "script-1",
            "title": "A história do café",
            "language": "pt",
            "keywords": ["coffee", "history"],
            "generation_settings": {"video_subject": "A história do café"},
        }
        normalised = normalise_saved_script(record, "---\nid: script-1\n---\n\nO roteiro guardado.")
        self.assertEqual(normalised["video_subject"], "A história do café")
        self.assertEqual(normalised["video_script"], "O roteiro guardado.")
        self.assertEqual(normalised["video_keywords"], "coffee, history")

    def test_only_content_has_all_three_settings_sections_missing(self):
        record = normalise_saved_script(
            {"title": "Tema", "video_script": "Roteiro", "video_keywords": "keyword"}
        )
        self.assertEqual(missing_content_fields(record), [])
        self.assertEqual(
            missing_setting_sections(record["generation_settings"]),
            ["Configurações de vídeo", "Configurações de áudio", "Configurações de legendas"],
        )

    def test_complete_script_has_no_missing_sections(self):
        settings = {
            key: True
            for key in (*VIDEO_SETTING_KEYS, *AUDIO_SETTING_KEYS, *SUBTITLE_SETTING_KEYS)
        }
        record = normalise_saved_script(
            {
                "title": "Tema completo",
                "video_subject": "Tema completo",
                "video_script": "Roteiro completo",
                "video_keywords": "complete",
                "generation_settings": settings,
            }
        )
        self.assertEqual(missing_content_fields(record), [])
        self.assertEqual(missing_setting_sections(record["generation_settings"]), [])

    def test_creation_page_exposes_saved_draft_tab_and_creates_normal_tasks(self):
        self.assertIn('"Gerar de Rascunho"', MAIN_SOURCE)
        # Commit 48adc9b ("fix: isolate video and shorts draft tab state")
        # adicionou o parâmetro prefix para isolar o estado da tab de rascunho
        # entre Criação de Vídeos e Criação de Shorts.
        self.assertIn('def render_video_from_draft(prefix: str = "new_video") -> None:', MAIN_SOURCE)
        self.assertIn("list_script_documents()", MAIN_SOURCE)
        self.assertIn("list_drafts()", MAIN_SOURCE)
        self.assertIn("create_tasks_for_batch(batch)", MAIN_SOURCE)
        # A chave do botão passou a ser parametrizada por prefix; na página de
        # Criação de Vídeos continua a resolver para "new_video_resume_submit".
        self.assertIn('key=f"{prefix}_resume_submit"', MAIN_SOURCE)
        self.assertIn('sections=selected_sections', MAIN_SOURCE)
        self.assertIn('"video_script": script', MAIN_SOURCE)
        self.assertIn('"video_keywords": keywords', MAIN_SOURCE)

    def test_draft_video_labels_are_translated_for_all_languages(self):
        languages = ("pt", "en", "zh", "de", "vi", "tr", "ru", "es", "id", "it")
        source = LANGUAGES_SOURCE.split("_DRAFT_VIDEO_TRANSLATIONS", 1)[1]
        for language in languages:
            block = source.split(f'    "{language}": {{', 1)[1].split("    },", 1)[0]
            self.assertIn('"Gerar de Rascunho"', block)
            self.assertIn('"Configurações a completar"', block)
            self.assertIn('"Continuar criação"', block)
            self.assertIn('"Gerar apenas o vídeo"', block)


    def test_resume_sections_multiselect_uses_session_state_only(self):
        """1.0.01: o warning de política do Streamlit exigia default= + pré-escrita.

        O multiselect `new_video_resume_sections` não pode passar `default=`
        (a key é escrita pelo seed `_seed_resume_video_settings` antes do
        widget); session_state é a fonte única da verdade, com guard canónico
        para o caso de a key ainda não existir.
        """
        block = MAIN_SOURCE.split('sections_key = f"{prefix}_resume_sections"', 1)[1].split("st.caption(", 1)[0]
        self.assertIn('if sections_key not in st.session_state:', block)
        self.assertIn("st.session_state[sections_key] = missing_sections", block)
        self.assertIn("key=sections_key", block)
        self.assertNotIn("default=", block)
        # o seed continua a ser o escritor canónico por registo (troca de
        # rascunho actualiza o multiselect via session_state, sem default=)
        self.assertIn(
            'st.session_state[f"{state_prefix}_sections"] = missing_setting_sections(generation_settings)',
            MAIN_SOURCE,
        )

    def test_streamlit_widget_policy_logger_is_silenced_surgically(self):
        """1.0.01: o logger de políticas de widgets é rebaixado para ERROR no
        import do módulo; erros reais do Streamlit continuam visíveis porque
        nenhum silenciamento genérico é usado."""
        guard = 'logging.getLogger("streamlit.elements.lib.policies").setLevel(logging.ERROR)'
        self.assertIn(guard, MAIN_SOURCE)
        # o guard fica no topo do módulo, depois do import do streamlit e
        # antes de qualquer render
        self.assertGreater(MAIN_SOURCE.index(guard), MAIN_SOURCE.index("import streamlit as st"))
        self.assertNotIn("logging.disable(", MAIN_SOURCE)
        self.assertNotIn('getLogger("streamlit").setLevel', MAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()
