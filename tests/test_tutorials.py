import unittest
from pathlib import Path

from hermes_ui.languages import LANGUAGE_CODES
from hermes_ui.tutorials import tutorial_body, tutorial_caption, tutorial_definition, tutorial_title


class TutorialContentTests(unittest.TestCase):
    def test_both_tutorials_have_localized_title_caption_and_body(self):
        for kind in ("kaggle", "apify"):
            for language in LANGUAGE_CODES:
                definition = tutorial_definition(kind, language)
                self.assertTrue(definition["title"], (kind, language))
                self.assertTrue(definition["caption"], (kind, language))
                self.assertGreater(len(definition["body"]), 500, (kind, language))
                self.assertEqual(tutorial_title(kind, language), definition["title"])
                self.assertEqual(tutorial_caption(kind, language), definition["caption"])
                self.assertEqual(tutorial_body(kind, language), definition["body"])

    def test_unknown_language_falls_back_to_portuguese(self):
        for kind in ("kaggle", "apify"):
            self.assertEqual(tutorial_definition(kind, "xx"), tutorial_definition(kind, "pt"))

    def test_kaggle_tutorial_contains_reference_project_and_token_steps(self):
        body = tutorial_body("kaggle", "pt")
        self.assertIn("johanfortus/Niche-Finder", body)
        self.assertIn("kaggle.com/settings/api", body)
        self.assertIn("Generate New Token", body)
        self.assertIn("Create Legacy API Key", body)
        self.assertIn("Kaggle Username", body)
        self.assertIn("Kaggle API Key", body)
        self.assertIn("Testar chamada API", body)

    def test_apify_tutorial_contains_n8n_workflow_and_safe_verification(self):
        body = tutorial_body("apify", "pt")
        self.assertIn("YTB Outlier Finder", body)
        self.assertIn("n8n.io/workflows/4187", body)
        self.assertIn("console.apify.com/settings/integrations", body)
        self.assertIn("api.apify.com/v2/users/me", body)
        self.assertIn("Authorization: Bearer", body)
        self.assertIn("não inicia actor", body)

    def test_main_routes_render_real_tutorials(self):
        main_source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn('"Kaggle": lambda: render_niche_tutorial("kaggle")', main_source)
        self.assertIn('"Apify": lambda: render_niche_tutorial("apify")', main_source)
        self.assertNotIn('"Tutorial Kaggle": lambda: render_edit_placeholder("Tutorial Kaggle", "")', main_source)
        self.assertNotIn('"Tutorial Apify": lambda: render_edit_placeholder("Tutorial Apify", "")', main_source)

    def test_all_languages_keep_the_external_sources(self):
        for kind in ("kaggle", "apify"):
            for language in LANGUAGE_CODES:
                body = tutorial_body(kind, language)
                self.assertIn("https://", body, (kind, language))
                self.assertIn("[1]", body, (kind, language))


if __name__ == "__main__":
    unittest.main()
