from __future__ import annotations

import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.influencers_ui import _image_input
from hermes_ui import influencers, media_generation, media_providers


class AIInfluencerRepositoryTests(unittest.TestCase):
    def test_validate_and_parse_supported_assets(self):
        image = influencers.validate_asset(" rosto final.png ", b"image-bytes")
        self.assertEqual(image["asset_type"], "image")
        self.assertEqual(image["original_name"], "rosto-final.png")
        markdown = influencers.parse_document("perfil.md", b"# Personagem\n\nBio")
        self.assertEqual(markdown["format"], "markdown")
        document = influencers.parse_document("perfil.json", b'{"age": 31, "style": "realista"}')
        self.assertEqual(document["value"]["age"], 31)
        with self.assertRaises(ValueError):
            influencers.parse_document("perfil.json", b"not-json")
        with self.assertRaises(ValueError):
            influencers.validate_asset("malware.exe", b"x")

    def test_sqlite_persists_character_multiple_assets_and_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(influencers, "STORAGE", root / "storage"):
                repository = influencers.SQLiteInfluencerRepository(root / "ai.db")
                self.assertTrue(repository.test_connection()["ok"])
                character = repository.create_influencer({"name": "Lia", "bio": "Criadora de viagens", "language": "pt-BR"})
                first = repository.save_asset(character["id"], "face.png", b"first-image")
                second = repository.save_asset(character["id"], "style.jpg", b"second-image")
                document = repository.save_asset(character["id"], "profile.md", b"# Lia\nEstilo editorial")
                duplicate = repository.save_asset(character["id"], "another-name.png", b"first-image")
                assets = repository.list_assets(character["id"])
                self.assertEqual(len(assets), 3)
                self.assertEqual(duplicate["id"], first["id"])
                self.assertTrue(Path(first["stored_path"]).is_file())
                self.assertTrue(Path(second["stored_path"]).is_file())
                self.assertEqual(document["asset_type"], "document")
                content = repository.create_content({"influencer_id": character["id"], "content_type": "video", "prompt": "caminhar na praia", "provider": "replicate", "model": "owner/model:version", "state": "queued"})
                updated = repository.update_content(content["id"], {"state": "completed", "artifact_path": str(root / "video.mp4")})
                self.assertEqual(updated["state"], "completed")
                self.assertEqual(repository.list_content(character["id"])[0]["artifact_path"], str(root / "video.mp4"))
                # O repositório delega o fecho das ligações sqlite3 ao GC (o with
                # do sqlite3 só faz commit); no Windows o ficheiro aberto impediria
                # a limpeza do TemporaryDirectory (WinError 32).
                gc.collect()

    def test_standalone_workflow_owner_keeps_motion_and_ugc_content_in_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(influencers, "STORAGE", root / "storage"):
                repository = influencers.SQLiteInfluencerRepository(root / "ai.db")
                owner_id = influencers.ensure_standalone_content_owner(repository)
                self.assertEqual(owner_id, influencers.STANDALONE_CONTENT_INFLUENCER_ID)
                self.assertEqual(len(repository.list_influencers()), 1)
                motion = repository.create_content({"influencer_id": owner_id, "content_type": "video", "provider": "kie_ai", "model": "kling-2.6/motion-control", "state": "running", "metadata": {"workflow": "motion_control"}})
                ugc = repository.create_content({"influencer_id": owner_id, "content_type": "video", "provider": "kie_ai", "model": "veo3_fast", "state": "completed", "metadata": {"workflow": "ugc_products", "task_ids": ["one", "two"]}})
                rows = repository.list_content(owner_id)
                self.assertEqual({row["id"] for row in rows}, {motion["id"], ugc["id"]})
                self.assertIn("motion_control", rows[1]["metadata_json"] + rows[0]["metadata_json"])
                self.assertIn("ugc_products", rows[1]["metadata_json"] + rows[0]["metadata_json"])
                # Idem: fechar ligações sqlite pendentes de GC antes da limpeza no Windows.
                gc.collect()

    def test_supabase_repository_uses_expected_tables_with_mock_client(self):
        class Query:
            def __init__(self, table: str, client: "FakeClient"):
                self.table = table
                self.client = client
                self.filters = []

            def select(self, columns: str):
                return self

            def limit(self, value: int):
                return self

            def order(self, *args, **kwargs):
                return self

            def eq(self, column: str, value: str):
                self.filters.append((column, value))
                return self

            def insert(self, payload):
                self.client.inserted.append((self.table, payload))
                return self

            def update(self, payload):
                self.client.updated.append((self.table, payload))
                return self

            def delete(self):
                return self

            def execute(self):
                if self.table == "influencers" and self.client.inserted:
                    return Mock(data=[self.client.inserted[-1][1]])
                return Mock(data=[])

        class FakeStorage:
            def from_(self, bucket):
                self.bucket = bucket
                return self

            def upload(self, path, content, options=None):
                self.uploaded = (path, content, options)

        class FakeClient:
            def __init__(self):
                self.inserted = []
                self.updated = []
                self.storage = FakeStorage()

            def table(self, name):
                return Query(name, self)

        client = FakeClient()
        repository = influencers.SupabaseInfluencerRepository("https://example.supabase.co", "secret", client=client)
        self.assertTrue(repository.test_connection()["ok"])
        character = repository.create_influencer({"name": "Mara"})
        self.assertEqual(character["name"], "Mara")
        self.assertEqual(client.inserted[0][0], "influencers")
        self.assertNotIn("secret", repr(client.inserted))

    def test_relative_sqlite_path_uses_persistent_storage_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            persistent_storage = Path(temp_dir) / "storage"
            with patch.object(influencers, "STORAGE", persistent_storage):
                expected = (persistent_storage / "state" / "ai_influencers.db").resolve()
                self.assertEqual(influencers.sqlite_path_from_settings({}), expected)
                self.assertEqual(influencers.sqlite_path_from_settings({"influencer_sqlite_path": "storage/state/ai_influencers.db"}), expected)
                self.assertEqual(influencers.SQLiteInfluencerRepository("storage/state/ai_influencers.db").path, expected)

    def test_backend_selector_is_exclusive_and_sqlite_is_defaultable(self):
        self.assertEqual(influencers.backend_name({"influencer_db_backend": "sqlite"}), "SQLite")
        self.assertEqual(influencers.backend_name({"influencer_db_backend": "Supabase"}), "SQLite")
        self.assertEqual(influencers.backend_name({"influencer_db_backend": "Supabase", "influencer_supabase_url": "https://example.supabase.co", "influencer_supabase_key": "key"}), "Supabase")
        fallback_status = influencers.backend_status({"influencer_db_backend": "Supabase"})
        self.assertEqual(fallback_status["backend"], "SQLite")
        self.assertTrue(fallback_status["configured"])
        status = influencers.backend_status({"influencer_db_backend": "SQLite", "influencer_sqlite_path": "storage/state/test.db"})
        self.assertTrue(status["configured"])

    def test_empty_or_missing_supabase_settings_open_local_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = {"influencer_sqlite_path": str(Path(temp_dir) / "local.db")}
            repository = influencers.get_repository(settings)
            self.assertIsInstance(repository, influencers.SQLiteInfluencerRepository)
            self.assertTrue(influencers.test_backend(settings)["ok"])
            # Idem: fechar ligações sqlite pendentes de GC antes da limpeza no Windows.
            gc.collect()


class ReplicateAdapterTests(unittest.TestCase):
    def test_replicate_video_prediction_uses_version_and_model_input(self):
        response = Mock(status_code=201)
        card = {
            "provider": "replicate",
            "api_style": "replicate",
            "api_key": "token",
            "base_url": "https://api.replicate.com/v1",
            "model": "owner/video-model:version-id",
        }
        with patch.object(media_generation.requests, "post", return_value=response) as post:
            media_generation._video_request(card, "walking", image_url="https://example.com/input.png")
        self.assertEqual(post.call_args.args[0], "https://api.replicate.com/v1/predictions")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["version"], "owner/video-model:version-id")
        self.assertEqual(body["input"]["image"], "https://example.com/input.png")

    def test_replicate_output_list_and_canceled_state_are_supported(self):
        self.assertEqual(media_generation._video_result({"id": "prediction-1", "output": ["https://example.com/video.mp4"]}), ("https://example.com/video.mp4", ""))
        self.assertEqual(media_generation.media_provider_definition("replicate").api_style, "replicate")
        self.assertIn("replicate", {item["code"] for item in media_providers.media_provider_catalog()})

    def test_replicate_image_prediction_is_polled_until_output(self):
        responses = [Mock(status_code=200, json=lambda: {"id": "prediction-1", "status": "processing"}), Mock(status_code=200, json=lambda: {"id": "prediction-1", "status": "succeeded", "output": ["https://example.com/image.png"]})]
        card = {"provider": "replicate", "api_style": "replicate", "api_key": "token", "base_url": "https://api.replicate.com/v1", "model": "owner/image:version"}
        with patch.object(media_generation.requests, "get", side_effect=responses) as get, patch.object(media_generation.time, "sleep"):
            result = media_generation._poll_image(card, "prediction-1", attempts=2, interval_seconds=0)
        self.assertEqual(result, (None, "https://example.com/image.png"))
        self.assertEqual(get.call_count, 2)

    def test_local_image_input_is_bounded_and_data_url_encoded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "small.png"
            path.write_bytes(b"png-bytes")
            value = _image_input({"stored_path": str(path), "mime_type": "image/png"})
        self.assertTrue(value.startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
