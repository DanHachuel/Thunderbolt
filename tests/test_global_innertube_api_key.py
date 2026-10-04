import tempfile
import unittest
from pathlib import Path

from integrations.youtube_direct_credentials import (
    account_innertube_api_key,
    document_status,
    save_credentials_document,
)


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
LANGUAGES_SOURCE = (ROOT / "hermes_ui" / "languages.py").read_text(encoding="utf-8")


class GlobalInnertubeApiKeyTests(unittest.TestCase):
    def test_google_accounts_ui_has_one_global_field_without_account_selector(self):
        # A assinatura ganhou parâmetros (include_innertube); fatiar sem os parênteses.
        start = MAIN_SOURCE.index("def render_google_accounts(")
        end = MAIN_SOURCE.find("\ndef ", start + 1)
        renderer = MAIN_SOURCE[start:end if end != -1 else None]

        self.assertIn('key="global_innertube_api_key"', renderer)
        self.assertIn('settings["direct_innertube_api_key"] = innertube_api_key_value.strip()', renderer)
        self.assertIn('Guardar INNERTUBE_API_KEY global', renderer)
        self.assertNotIn('key="innertube_key_account"', renderer)
        self.assertNotIn('selected_key_account_id', renderer)
        self.assertNotIn('st.selectbox("Conta Google/YouTube"', renderer)
        self.assertNotIn('key=f"innertube_api_key_{selected_key_account_id}"', renderer)

    def test_google_account_cards_show_shared_configured_badge(self):
        start = MAIN_SOURCE.index("def render_google_accounts(")
        end = MAIN_SOURCE.find("\ndef ", start + 1)
        renderer = MAIN_SOURCE[start:end if end != -1 else None]

        self.assertIn('with st.container(border=True):', renderer)
        # Os cartões mostram dois badges: estado Google (client_id/secret) e estado
        # de upload (documento de credenciais); ambos derivam de flags *_ready.
        self.assertIn('google_ready = bool(', renderer)
        self.assertIn('google_status_label = "Configured" if google_ready', renderer)
        self.assertIn('_api_status_badge(google_status_label, "ready" if google_ready else "missing")', renderer)
        self.assertIn('with st.expander("Detalhes da conta Google", expanded=False):', renderer)

    def test_global_innertube_key_shows_shared_configured_badge(self):
        start = MAIN_SOURCE.index("def render_google_accounts(")
        end = MAIN_SOURCE.find("\ndef ", start + 1)
        renderer = MAIN_SOURCE[start:end if end != -1 else None]

        self.assertIn('_render_credential_status(current_innertube_api_key)', renderer)
        self.assertIn('innertube_status_cols = st.columns([3.2, 1.2])', renderer)

    def test_global_key_takes_precedence_over_legacy_account_values(self):
        account = {"id": "one", "innertube_api_key": "legacy-account-key"}
        document = {"INNERTUBE_API_KEY": "legacy-document-key"}
        settings = {"direct_innertube_api_key": "global-key"}

        self.assertEqual(account_innertube_api_key(account, document, settings), "global-key")
        self.assertEqual(
            account_innertube_api_key(
                {"id": "two", "innertube_api_key": "another-legacy-key"},
                {"INNERTUBE_API_KEY": "another-document-key"},
                settings,
            ),
            "global-key",
        )

    def test_legacy_account_key_remains_readable_only_for_migration(self):
        self.assertEqual(
            account_innertube_api_key({"innertube_api_key": "legacy-key"}, {}, {}),
            "legacy-key",
        )
        self.assertEqual(
            account_innertube_api_key({}, {"INNERTUBE_API_KEY": "legacy-document-key"}, {}),
            "legacy-document-key",
        )

    def test_first_legacy_account_value_is_shared_during_migration(self):
        settings = {
            "youtube_batch_accounts": [
                {"id": "first", "innertube_api_key": "legacy-global-key"},
                {"id": "second", "innertube_api_key": "different-legacy-key"},
            ]
        }
        self.assertEqual(account_innertube_api_key({"id": "first"}, {}, settings), "legacy-global-key")
        self.assertEqual(account_innertube_api_key({"id": "second"}, {}, settings), "legacy-global-key")

    def test_document_status_uses_global_key_for_multiple_accounts(self):
        cookies = {key: f"value-{key}" for key in ("SID", "SSID", "HSID", "APISID", "SAPISID")}
        document = {"sessionInfo": "session", "cookies": cookies, "delegated_session_ids": {}}
        settings = {"direct_innertube_api_key": "one-global-key"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = {"id": "account-one", "email": "one@example.com"}
            second = {"id": "account-two", "email": "two@example.com"}
            save_credentials_document(root, first, document)
            save_credentials_document(root, second, document)

            first_status = document_status(root, first, settings=settings)
            second_status = document_status(root, second, settings=settings)

        self.assertTrue(first_status["has_innertube_api_key"])
        self.assertTrue(second_status["has_innertube_api_key"])
        self.assertEqual(first_status["innertube_api_key"], "one-global-key")
        self.assertEqual(second_status["innertube_api_key"], "one-global-key")

    def test_global_key_is_translated_for_all_supported_languages(self):
        source_keys = (
            "Esta é uma chave API global do YouTube:",
            "Chave global usada pelo Upload directo para todas as contas Google/YouTube.",
            "Guardar INNERTUBE_API_KEY global",
            "INNERTUBE_API_KEY global guardada para todas as contas Google/YouTube e para todo o sistema.",
        )
        self.assertIn("_GLOBAL_INNERTUBE_TRANSLATIONS", LANGUAGES_SOURCE)
        for language_code in ("pt", "en", "zh", "de", "vi", "tr", "ru", "es", "id", "it"):
            self.assertIn(f'    "{language_code}": {{', LANGUAGES_SOURCE)
        for source_key in source_keys:
            self.assertIn(source_key, LANGUAGES_SOURCE)


if __name__ == "__main__":
    unittest.main()

