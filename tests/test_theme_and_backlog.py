from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CONFIG_SOURCE = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
LANGUAGES_SOURCE = (ROOT / "hermes_ui" / "languages.py").read_text(encoding="utf-8")


class ThemeAndBacklogTests(unittest.TestCase):
    def test_backlog_uses_canonical_title(self):
        self.assertIn('st.subheader("Backlog Videos")', MAIN_SOURCE)
        self.assertNotIn('st.subheader("Backlog Vídeos")', MAIN_SOURCE)
        self.assertNotIn('st.subheader("Vídeos e backlog")', MAIN_SOURCE)

    def test_canonical_backlog_key_is_translated_for_all_languages(self):
        for language_code in ("pt", "en", "zh", "de", "vi", "tr", "ru", "es", "id", "it"):
            self.assertIn(f'"{language_code}"', LANGUAGES_SOURCE)
        self.assertIn('UI_TRANSLATIONS[_language_code]["Backlog Videos"]', LANGUAGES_SOURCE)

    def test_backlog_cards_match_automation_start_stop_controls(self):
        self.assertIn('key=f"automation_start_{task[\'id\']}"', MAIN_SOURCE)
        self.assertIn('key=f"automation_stop_{task[\'id\']}"', MAIN_SOURCE)
        self.assertIn('disabled=state not in {"to_do", "blocked", "failed"}', MAIN_SOURCE)
        self.assertIn('disabled=state != "doing"', MAIN_SOURCE)
        self.assertNotIn('key=f"start_{task[\'id\']}"', MAIN_SOURCE)
        self.assertNotIn('key=f"stop_{task[\'id\']}"', MAIN_SOURCE)

    def test_streamlit_exposes_switchable_light_and_dark_themes(self):
        self.assertIn("[theme.dark]", CONFIG_SOURCE)
        self.assertIn("[theme.light]", CONFIG_SOURCE)
        self.assertIn('[client]\ntoolbarMode = "auto"', CONFIG_SOURCE)
        self.assertIn('hideWelcomeMessage = true', CONFIG_SOURCE)
        self.assertNotIn('hideWarningOnDirectExecution', CONFIG_SOURCE)
        self.assertNotIn('base = "dark"', CONFIG_SOURCE.split("[theme.dark]", 1)[0])
        theme_root = CONFIG_SOURCE.split("[theme.dark]", 1)[0]
        self.assertNotIn('base = "dark"', theme_root)
        self.assertNotIn('base = "light"', theme_root)

    def test_dashboard_cards_do_not_force_dark_palette(self):
        self.assertIn(".content-card {", MAIN_SOURCE)
        self.assertIn("background:color-mix(in srgb, currentColor 5%, transparent)", MAIN_SOURCE)
        self.assertIn("background:rgba(128,128,128,.10)", MAIN_SOURCE)
        self.assertIn("border:1px solid rgba(128,128,128,.28)", MAIN_SOURCE)
        self.assertIn("box-shadow:0 4px 14px rgba(0,0,0,.12)", MAIN_SOURCE)
        self.assertNotIn("background:#121b26", MAIN_SOURCE)
        self.assertNotIn("color:#f4f8fb; font-size:1.8rem", MAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()
