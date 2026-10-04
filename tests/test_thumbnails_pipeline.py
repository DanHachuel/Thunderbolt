import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from hermes_ui.creative_generation import generate_thumbnail_prompt
from hermes_ui.thumbnail_generation import generate_thumbnail_image
from hermes_ui.thumbnails import (
    generate_thumbnail_for_task,
    list_thumbnail_tasks,
    normalize_thumbnail_task,
    regenerate_thumbnail,
    regenerate_thumbnail_lettering,
    regenerate_thumbnail_prompt,
    regenerate_thumbnail_prompt_and_image,
    upload_thumbnail_image,
)


def _fake_update_json_factory(tasks, captured):
    """Mock de storage.update_json com a semântica actual (§2.3 da tarefa):
    aplica o mutator ao snapshot de tarefas em memória, regista o documento
    persistido (substitui os antigos mocks de write_json, que a produção
    deixou de chamar) e devolve o resultado do mutator, como o storage real."""
    def fake_update_json(_name, _default, callback):
        result = callback(tasks)
        captured["saved"] = tasks
        return result
    return fake_update_json


class ThumbnailPipelineTests(unittest.TestCase):
    def test_normalize_prefers_title_and_artifact_fallback(self):
        task = {
            "id": "video-1",
            "topic": "Tema de fallback",
            "channel_name": "Canal Teste",
            "thumbnail_status": "generated",
            "thumbnail_prompt": "A cinematic thumbnail",
            "artifacts": {"thumbnail": "missing.jpg"},
        }
        normalized = normalize_thumbnail_task(task)
        self.assertEqual(normalized["title"], "Tema de fallback")
        self.assertEqual(normalized["prompt"], "A cinematic thumbnail")
        self.assertEqual(normalized["task_id"], "video-1")

    def test_list_includes_prompt_only_and_generated_tasks_but_not_unrelated_tasks(self):
        tasks = [
            {"id": "with-prompt", "title": "Com prompt", "thumbnail_prompt": "prompt", "thumbnail_status": "prompt_ready"},
            {"id": "with-image", "title": "Com imagem", "artifacts": {"thumbnail": "thumb.jpg"}, "thumbnail_status": "generated"},
            {"id": "unrelated", "title": "Sem thumbnail"},
        ]
        with patch("hermes_ui.thumbnails.read_json", return_value=tasks):
            records = list_thumbnail_tasks()
        self.assertEqual([record["task_id"] for record in records], ["with-prompt", "with-image"])

    def test_regenerate_updates_task_without_removing_other_fields(self):
        tasks = [{
            "id": "video-1",
            "title": "Título do vídeo",
            "topic": "Tema",
            "thumbnail_prompt": "new prompt",
            "thumbnail_status": "prompt_ready",
            "thumbnail_variant": {"image_prompt": "new prompt", "overlay_text": "Texto"},
            "thumbnail_variants": [{"image_prompt": "new prompt"}],
            "artifacts": {"script": "/tmp/script.txt"},
            "state": "doing",
        }]
        captured = {}
        with tempfile.TemporaryDirectory() as directory:
            generated_path = Path(directory) / "new-thumbnail.jpg"

            def fake_generate(settings, prompt, *, topic, variant_index, **kwargs):
                captured.update({"settings": settings, "prompt": prompt, "topic": topic, "variant_index": variant_index, "kwargs": kwargs})
                return generated_path

            with patch("hermes_ui.thumbnails.read_json", return_value=tasks), patch("hermes_ui.thumbnails.write_json", side_effect=lambda _name, value: captured.update({"saved": value})), patch("hermes_ui.thumbnails.update_json", side_effect=_fake_update_json_factory(tasks, captured)), patch("hermes_ui.thumbnails.thumbnail_blueprint_for_task", return_value={}), patch("hermes_ui.thumbnails.generate_thumbnail_image", side_effect=fake_generate):
                task, image_path = regenerate_thumbnail("video-1", {"gemini_image_api_key": "key"})

        self.assertEqual(image_path, generated_path)
        self.assertEqual(captured["prompt"], "new prompt")
        self.assertEqual(captured["topic"], "Título do vídeo")
        self.assertEqual(captured["variant_index"], 0)
        self.assertEqual(captured["kwargs"]["lettering_text"], "Texto")
        self.assertEqual(task["state"], "doing")
        self.assertEqual(task["thumbnail_status"], "generated")
        self.assertEqual(task["artifacts"]["script"], "/tmp/script.txt")
        self.assertEqual(task["artifacts"]["thumbnail"], str(generated_path))
        self.assertEqual(task["thumbnail_variant"]["image_path"], str(generated_path))
        self.assertEqual(captured["saved"][0]["thumbnail_status"], "generated")

    def test_generate_image_persists_generated_source(self):
        tasks = [{
            "id": "video-1",
            "title": "Título",
            "topic": "Tema",
            "thumbnail_prompt": "prompt",
            "thumbnail_status": "prompt_ready",
            "artifacts": {},
        }]
        generated_path = Path("/tmp/generated-thumbnail.jpg")
        captured = {}
        with patch("hermes_ui.thumbnails.read_json", return_value=tasks), patch("hermes_ui.thumbnails.write_json", side_effect=lambda _name, value: captured.update({"saved": value})), patch("hermes_ui.thumbnails.update_json", side_effect=_fake_update_json_factory(tasks, captured)), patch("hermes_ui.thumbnails._archive_image"), patch("hermes_ui.thumbnails.generate_thumbnail_image", return_value=generated_path):
            task, image_path = generate_thumbnail_for_task("video-1", {"gemini_image_api_key": "key"})
        self.assertEqual(image_path, generated_path)
        self.assertEqual(task["thumbnail_source"], "generated")
        self.assertEqual(task["artifacts"]["thumbnail"], str(generated_path))
        self.assertEqual(captured["saved"][0]["thumbnail_status"], "generated")

    def test_thumbnail_prompt_has_lettering_fallback_when_provider_omits_overlay(self):
        with patch(
            "hermes_ui.creative_generation._chat_json",
            return_value={"image_prompt": "cinematic man reading a book, high contrast"},
        ):
            variant = generate_thumbnail_prompt({}, {}, "Man With Book")
        self.assertTrue(variant["overlay_text"])
        self.assertEqual(variant["overlay_text"], "Man With Book")
        self.assertTrue(variant["lettering_prompt"])

    def test_image_payload_contains_exact_required_lettering(self):
        image_payload = {
            "status": "completed",
            "steps": [{"content": [{"type": "image", "data": base64.b64encode(b"image").decode("ascii")}]}],
        }
        response = SimpleNamespace(status_code=200, json=lambda: image_payload)
        with tempfile.TemporaryDirectory() as directory:
            with patch("hermes_ui.thumbnail_generation.STORAGE", Path(directory)), patch("hermes_ui.thumbnail_generation.ensure_storage"), patch("hermes_ui.thumbnail_generation.requests.post", return_value=response) as request:
                image_path = generate_thumbnail_image(
                    {"gemini_image_api_key": "key"},
                    "man reading a book, cinematic, high contrast",
                    topic="Deep Focus Habits",
                    lettering_text="FOCUS NOW",
                    lettering_prompt="Bold white letters with a black outline.",
                )
                self.assertTrue(image_path.is_file())
                image_bytes = image_path.read_bytes()
        body = request.call_args.kwargs["json"]
        prompt = body["input"]
        self.assertIn("MANDATORY LETTERING LAYER", prompt)
        self.assertIn("EXACT HEADLINE TO RENDER: <<<FOCUS NOW>>>", prompt)
        self.assertIn("MUST visibly contain readable lettering", prompt)
        self.assertIn("Bold white letters with a black outline.", prompt)
        self.assertEqual(image_bytes, b"image")

    def test_image_payload_falls_back_to_non_empty_lettering_for_legacy_task(self):
        image_payload = {
            "status": "completed",
            "steps": [{"content": [{"type": "image", "data": base64.b64encode(b"image").decode("ascii")}]}],
        }
        response = SimpleNamespace(status_code=200, json=lambda: image_payload)
        with tempfile.TemporaryDirectory() as directory:
            with patch("hermes_ui.thumbnail_generation.STORAGE", Path(directory)), patch("hermes_ui.thumbnail_generation.ensure_storage"), patch("hermes_ui.thumbnail_generation.requests.post", return_value=response) as request:
                generate_thumbnail_image(
                    {"gemini_image_api_key": "key"},
                    "person reading a book",
                    topic="Man With Book",
                )
        prompt = request.call_args.kwargs["json"]["input"]
        self.assertIn("EXACT HEADLINE TO RENDER: <<<MAN WITH BOOK>>>", prompt)

    def test_prompt_regeneration_persists_new_variant_and_image(self):
        tasks = [{
            "id": "video-1",
            "title": "Título",
            "topic": "Tema",
            "thumbnail_prompt": "old prompt",
            "thumbnail_variant": {"image_prompt": "old prompt", "overlay_text": "Old"},
            "thumbnail_variants": [{"image_prompt": "old prompt"}],
            "artifacts": {"script": "/tmp/script.txt"},
        }]
        generated_path = Path("/tmp/prompt-regenerated.jpg")
        variant = {"image_prompt": "new prompt", "overlay_text": "New", "lettering_prompt": "short text"}
        captured = {}
        with patch("hermes_ui.thumbnails.read_json", return_value=tasks), patch("hermes_ui.thumbnails.write_json", side_effect=lambda _name, value: captured.update({"saved": value})), patch("hermes_ui.thumbnails.update_json", side_effect=_fake_update_json_factory(tasks, captured)), patch("hermes_ui.thumbnails._archive_image"), patch("hermes_ui.thumbnails.generate_thumbnail_image", return_value=generated_path):
            task, _image_path = regenerate_thumbnail_prompt_and_image("video-1", {"gemini_image_api_key": "key"}, variant)
        self.assertEqual(task["thumbnail_source"], "prompt_regenerated")
        self.assertEqual(task["thumbnail_prompt"], "new prompt")
        self.assertEqual(task["thumbnail_text"], "New")
        self.assertEqual(task["thumbnail_variants"][0]["image_path"], str(generated_path))
        self.assertEqual(captured["saved"][0]["artifacts"]["script"], "/tmp/script.txt")

    def test_prompt_only_regeneration_preserves_active_image_and_skips_image_generation(self):
        tasks = [{
            "id": "video-1",
            "title": "Título",
            "topic": "Tema",
            "thumbnail_prompt": "old prompt",
            "thumbnail_status": "generated",
            "thumbnail_variant": {"image_prompt": "old prompt", "overlay_text": "Old", "image_path": "/tmp/existing.jpg"},
            "thumbnail_variants": [{"image_prompt": "old prompt", "image_path": "/tmp/existing.jpg"}],
            "thumbnail_path": "/tmp/existing.jpg",
            "artifacts": {"thumbnail": "/tmp/existing.jpg", "script": "/tmp/script.txt"},
        }]
        new_variant = {
            "image_prompt": "new prompt",
            "overlay_text": "New",
            "lettering_prompt": "new lettering",
        }
        captured = {}
        with patch("hermes_ui.thumbnails.read_json", return_value=tasks), patch("hermes_ui.thumbnails.write_json", side_effect=lambda _name, value: captured.update({"saved": value})), patch("hermes_ui.thumbnails.update_json", side_effect=_fake_update_json_factory(tasks, captured)), patch("hermes_ui.thumbnails.generate_thumbnail_prompt", return_value=new_variant) as prompt_generator, patch("hermes_ui.thumbnails.generate_thumbnail_image") as image_generator:
            task, variant = regenerate_thumbnail_prompt(
                "video-1",
                {"llm": "settings"},
                {"id": "channel-1", "name": "Canal"},
                blueprint={"id": "blueprint-1"},
                language="en",
            )

        prompt_generator.assert_called_once()
        image_generator.assert_not_called()
        self.assertEqual(variant, new_variant)
        self.assertEqual(task["thumbnail_status"], "prompt_ready")
        self.assertEqual(task["thumbnail_source"], "prompt_regenerated")
        self.assertEqual(task["artifacts"]["thumbnail"], "/tmp/existing.jpg")
        self.assertEqual(task["thumbnail_path"], "/tmp/existing.jpg")
        self.assertEqual(task["thumbnail_variant"]["image_path"], "/tmp/existing.jpg")
        self.assertEqual(task["thumbnail_prompt"], "new prompt")
        self.assertEqual(task["thumbnail_text"], "New")
        self.assertEqual(captured["saved"][0]["artifacts"]["script"], "/tmp/script.txt")

    def test_lettering_edit_uses_existing_image_as_reference_and_separates_layers(self):
        tasks = [{
            "id": "video-1",
            "title": "Título",
            "topic": "Tema",
            "thumbnail_prompt": "base image prompt",
            "thumbnail_variant": {"image_prompt": "base image prompt", "overlay_text": "Old"},
            "artifacts": {},
        }]
        generated_path = Path("/tmp/lettering-regenerated.jpg")
        captured = {}
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.jpg"
            existing.write_bytes(b"image")
            tasks[0]["artifacts"]["thumbnail"] = str(existing)
            with patch("hermes_ui.thumbnails.read_json", return_value=tasks), patch("hermes_ui.thumbnails.write_json"), patch("hermes_ui.thumbnails.update_json", side_effect=_fake_update_json_factory(tasks, captured)), patch("hermes_ui.thumbnails._archive_image"), patch("hermes_ui.thumbnails.generate_thumbnail_image", side_effect=lambda _settings, prompt, **kwargs: captured.update({"prompt": prompt, "kwargs": kwargs}) or generated_path):
                task, _image_path = regenerate_thumbnail_lettering("video-1", {"gemini_image_api_key": "key"})
        self.assertIn("BASE IMAGE LAYER", captured["prompt"])
        self.assertIn("LETTERING EDIT LAYER", captured["prompt"])
        self.assertEqual(captured["kwargs"]["reference_image"], existing)
        self.assertEqual(task["thumbnail_source"], "lettering_regenerated")
        self.assertEqual(task["thumbnail_variant"]["image_prompt"], "base image prompt")

    def test_lettering_edit_locks_requested_language(self):
        tasks = [{
            "id": "video-language",
            "title": "Título",
            "topic": "Tema",
            "language": "en",
            "thumbnail_prompt": "base image prompt",
            "thumbnail_variant": {"image_prompt": "base image prompt", "overlay_text": "Old"},
            "artifacts": {"thumbnail": "/tmp/existing-language.jpg"},
        }]
        captured = {}
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing.jpg"
            existing.write_bytes(b"image")
            tasks[0]["artifacts"]["thumbnail"] = str(existing)
            generated = Path(directory) / "generated.jpg"
            with patch("hermes_ui.thumbnails.read_json", return_value=tasks), patch("hermes_ui.thumbnails.update_json", side_effect=lambda _name, _default, callback: callback(tasks)), patch("hermes_ui.thumbnails._archive_image"), patch("hermes_ui.thumbnails._generate_image_with_pool", side_effect=lambda _settings, prompt, **kwargs: captured.update({"prompt": prompt, "kwargs": kwargs}) or generated):
                regenerate_thumbnail_lettering("video-language", {}, language="en")
        self.assertIn("LANGUAGE LOCK", captured["prompt"])
        self.assertIn("English (en)", captured["prompt"])

    def test_upload_image_persists_uploaded_source_and_preserves_other_artifacts(self):
        tasks = [{
            "id": "video-1",
            "title": "Título",
            "thumbnail_prompt": "prompt",
            "thumbnail_variant": {"image_prompt": "prompt"},
            "artifacts": {"script": "/tmp/script.txt"},
        }]
        captured = {}
        with tempfile.TemporaryDirectory() as directory:
            with patch("hermes_ui.thumbnails.STORAGE", Path(directory)), patch("hermes_ui.thumbnails.read_json", return_value=tasks), patch("hermes_ui.thumbnails.write_json", side_effect=lambda _name, value: captured.update({"saved": value})), patch("hermes_ui.thumbnails.update_json", side_effect=_fake_update_json_factory(tasks, captured)), patch("hermes_ui.thumbnails._archive_image"):
                task, image_path = upload_thumbnail_image("video-1", b"fake image", "custom.png", "image/png")
            self.assertTrue(image_path.is_file())
            self.assertEqual(image_path.read_bytes(), b"fake image")
        self.assertEqual(task["thumbnail_source"], "uploaded")
        self.assertEqual(task["artifacts"]["script"], "/tmp/script.txt")
        self.assertEqual(captured["saved"][0]["thumbnail_status"], "generated")

    def test_regenerate_requires_prompt(self):
        tasks = [{"id": "video-2", "title": "Sem prompt", "thumbnail_status": "not_generated"}]
        with patch("hermes_ui.thumbnails.read_json", return_value=tasks), self.assertRaisesRegex(RuntimeError, "não tem um prompt"):
            regenerate_thumbnail("video-2", {})


if __name__ == "__main__":
    unittest.main()
