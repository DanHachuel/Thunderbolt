from __future__ import annotations

import json
from pathlib import Path


def test_storage_and_batch_modes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import create_batch, create_channel, create_tasks_for_batch, transition_task

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    channel_a = create_channel("Canal A")
    channel_b = create_channel("Canal B")

    single = create_batch("single", [channel_a["id"]], "Tema A", 1, {})
    assert len(create_tasks_for_batch(single)) == 1

    same = create_batch("same_channel", [channel_a["id"]], "Tema B", 3, {})
    assert len(create_tasks_for_batch(same)) == 3

    general = create_batch("general", [channel_a["id"], channel_b["id"]], "Tema C", 99, {})
    assert len(create_tasks_for_batch(general)) == 2

    task_id = storage.read_json("tasks.json")[0]["id"]
    assert transition_task(task_id, "doing")["state"] == "doing"
    assert transition_task(task_id, "blocked")["state"] == "blocked"


def test_retry_of_failed_task_clears_failure_without_storing_current_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import retry_task_with_current_settings

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    storage.write_json("tasks.json", [{
        "id": "video_retry_current_settings",
        "state": "failed",
        "stage": "thumbnail",
        "artifacts": {"video": "/tmp/ready.mp4"},
        "error": "API/provider: Nano Banana",
        "failure_api": "Nano Banana API",
        "failure_provider": "nano_banana",
        "failure_service": "Thumbnail",
        "failure_config_fields": "gemini_image_api_key",
    }])

    retried = retry_task_with_current_settings("video_retry_current_settings")

    assert retried is not None
    assert retried["state"] == "to_do"
    assert retried["stage"] == "thumbnail"
    assert retried["artifacts"] == {"video": "/tmp/ready.mp4"}
    assert retried["retry_count"] == 1
    assert retried["retry_config_source"] == "settings.json_at_execution"
    assert retried["error"] is None
    assert all(field not in retried for field in ("failure_api", "failure_provider", "failure_service", "failure_config_fields"))
    assert "api_key" not in retried


def test_remake_refreshes_current_channel_video_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import remake_video_task

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    storage.write_json("channels.json", [{
        "id": "channel-current",
        "default_enable_subtitles": False,
        "default_subtitle_position": "Top",
        "default_background_music_source": "Sem música",
        "default_background_music_volume": "0%",
        "default_thumbnail_blueprint_id": "thumb-modern",
        "default_voice": "voice-current",
        "style_wide": "pexels",
    }])
    storage.write_json("tasks.json", [{
        "id": "video-remake-current-settings",
        "channel_id": "channel-current",
        "state": "done",
        "generation_settings": {
            "enable_subtitles": True,
            "background_music_source": "Random Background Music",
        },
        "thumbnail_blueprint_id": "thumb-old",
        "voice": "voice-old",
        "artifacts": {
            "script": "/tmp/script.md",
            "audio": "/tmp/old.mp3",
            "narration": "/tmp/old-narration.wav",
            "video": "/tmp/old.mp4",
            "upload": "/tmp/upload.json",
        },
    }])

    remade = remake_video_task("video-remake-current-settings")

    assert remade["state"] == "to_do"
    assert remade["generation_settings"]["enable_subtitles"] is False
    assert remade["generation_settings"]["subtitle_position"] == "Top"
    assert remade["generation_settings"]["background_music_source"] == "Sem música"
    assert remade["generation_settings"]["background_music_volume"] == "0%"
    assert remade["thumbnail_blueprint_id"] == "thumb-modern"
    assert remade["voice"] == "voice-current"
    assert remade["artifacts"] == {"script": "/tmp/script.md"}
    assert remade["audio_regeneration_requested"] is True
    assert "audio_regeneration_requested_at" in remade


def test_manual_stop_marks_user_reason_but_keeps_queue_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import stop_task_by_user

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    storage.write_json("tasks.json", [{"id": "video_manual_stop", "state": "doing", "topic": "Tema"}])

    stopped = stop_task_by_user("video_manual_stop")

    assert stopped["state"] == "blocked"
    assert stopped["stop_reason"] == "user"
    assert storage.read_json("tasks.json")[0]["stop_reason"] == "user"


def test_blueprint_json_is_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    target = storage.BLUEPRINTS / "importados" / "blueprint.json"
    target.write_text(json.dumps({"name": "Teste", "unknown_field": {"keep": True}}), encoding="utf-8")
    assert storage.load_blueprint_file(target)["unknown_field"]["keep"] is True


def test_seed_blueprints_are_initialized_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    imported = sorted((storage.BLUEPRINTS / "importados").glob("*.json"))
    assert len(imported) == 14

    preserved = imported[0]
    preserved.write_text('{"name": "personalizado"}\n', encoding="utf-8")
    storage.ensure_storage()
    assert storage.load_blueprint_file(preserved)["name"] == "personalizado"


def test_blueprint_creation_modes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import blueprints, storage
    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()

    blueprint, branding = blueprints.create_blueprint_from_link("https://youtu.be/abc123", "história", "Português (pt-BR)", False)
    assert blueprint["metadata"]["input_type"] == "video"
    assert branding is None
    blueprint_path, branding_path = blueprints.save_generated_blueprint(blueprint)
    assert blueprint_path.exists()
    assert branding_path is None

    blueprint2, branding2 = blueprints.create_blueprint_from_link("https://www.youtube.com/@canal", "filosofia", "Português (pt-BR)", True, "Canal Exemplo", "Meu Blueprint Filosofia")
    assert blueprint2["name"] == "Meu Blueprint Filosofia"
    assert branding2 is not None
    blueprint_path2, branding_path2 = blueprints.save_generated_blueprint(blueprint2, branding2)
    assert blueprint_path2.name.startswith("meu-blueprint-filosofia-")
    assert branding_path2 is not None and branding_path2.exists()
    assert len(blueprints.list_branding_files()) == 1


def test_automation_defaults_are_carried_into_created_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import create_batch, create_channel, create_tasks_for_batch, update_channel

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    channel = create_channel("Canal automático", metadata={
        "default_blueprint_id": "bp_default",
        "default_voice": "pt-BR-FranciscaNeural-Female",
        "default_enable_subtitles": True,
        "default_subtitle_position": "Top",
        "default_background_music_source": "Sem música",
        "default_background_music_volume": "0%",
        "automation_on": True,
        "automation_time": "08:30",
    })
    update_channel(channel["id"], {"automation_on": True, "automation_time": "08:30"})
    batch = create_batch("single", [channel["id"]], "Tema automático", 1, {"language": "36 – Português (Brasil)"})
    task = create_tasks_for_batch(batch)[0]

    assert task["automation_on"] is True
    assert task["automation_time"] == "08:30"
    assert task["blueprint_id"] == "bp_default"
    assert task["voice"] == "pt-BR-FranciscaNeural-Female"
    assert task["generation_settings"]["enable_subtitles"] is True
    assert task["generation_settings"]["subtitle_position"] == "Top"
    assert task["generation_settings"]["background_music_source"] == "Sem música"
    assert task["generation_settings"]["background_music_volume"] == "0%"


def test_automation_channel_subtitle_defaults_override_stale_payload_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import create_batch, create_channel, create_tasks_for_batch

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    channel = create_channel("Canal com legendas", metadata={
        "default_enable_subtitles": True,
        "default_subtitle_position": "Top",
        "default_subtitle_font": "Arial.ttf",
        "default_background_music_source": "Sem música",
        "default_background_music_volume": "0%",
    })
    batch = create_batch("single", [channel["id"]], "Tema", 1, {
        "automation_worker": True,
        "channel_payloads": {channel["id"]: {
            "generation_settings": {
                "enable_subtitles": False,
                "subtitle_position": "Bottom",
                "subtitle_font": "OldFont.ttf",
                "background_music_source": "Random Background Music",
                "background_music_volume": "80%",
            },
        }},
    })

    task = create_tasks_for_batch(batch)[0]

    assert task["automation_worker"] is True
    assert task["generation_settings"]["enable_subtitles"] is True
    assert task["generation_settings"]["subtitle_position"] == "Top"
    assert task["generation_settings"]["subtitle_font"] == "Arial.ttf"
    assert task["generation_settings"]["background_music_source"] == "Sem música"
    assert task["generation_settings"]["background_music_volume"] == "0%"


def test_set_channel_defaults_syncs_aliases_and_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import create_batch, create_channel, create_tasks_for_batch, set_channel_defaults

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    channel = create_channel("Canal com defaults")
    updated = set_channel_defaults(channel["id"], "BlueprintCocomelon", "pt-BR-FranciscaNeural-Female")

    assert updated["blueprint_id"] == "BlueprintCocomelon"
    assert updated["default_blueprint_id"] == "BlueprintCocomelon"
    assert updated["voice"] == "pt-BR-FranciscaNeural-Female"
    assert updated["default_voice"] == "pt-BR-FranciscaNeural-Female"

    batch = create_batch("single", [channel["id"]], "Tema", 1, {})
    task = create_tasks_for_batch(batch)[0]
    assert task["blueprint_id"] == "BlueprintCocomelon"
    assert task["voice"] == "pt-BR-FranciscaNeural-Female"


def test_delete_channel_removes_only_selected_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import create_channel, delete_channel

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    first = create_channel("Canal para apagar")
    second = create_channel("Canal preservado")
    storage.write_json("tasks.json", [{"id": "video_1", "channel_id": first["id"]}])

    removed = delete_channel(first["id"])

    assert removed["id"] == first["id"]
    assert [item["id"] for item in storage.read_json("channels.json")] == [second["id"]]
    assert storage.read_json("tasks.json")[0]["channel_id"] == first["id"]
    assert delete_channel("channel_inexistente") is None


def test_delete_task_removes_selected_video_from_tasks_and_queues(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import delete_task

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    storage.write_json("tasks.json", [
        {"id": "video_remove", "state": "failed", "title": "Remover"},
        {"id": "video_keep", "state": "to_do", "title": "Manter"},
    ])
    storage.write_json("queues.json", {"script": ["video_remove", "video_keep"], "video": ["video_remove"]})

    removed = delete_task("video_remove")

    assert removed["id"] == "video_remove"
    assert [item["id"] for item in storage.read_json("tasks.json")] == ["video_keep"]
    queues = storage.read_json("queues.json")
    assert queues == {"script": ["video_keep"], "video": []}
    assert delete_task("video_missing") is None


def test_delete_task_rejects_running_video_until_it_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import delete_task

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.ensure_storage()
    storage.write_json("tasks.json", [{"id": "video_running", "state": "doing"}])

    import pytest
    with pytest.raises(ValueError, match="Pare a tarefa"):
        delete_task("video_running")

    assert storage.read_json("tasks.json")[0]["id"] == "video_running"


def test_general_batch_uses_independent_channel_payloads(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import create_batch, create_channel, create_tasks_for_batch

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    first = create_channel("Canal História", metadata={"default_blueprint_id": "bp_history"})
    second = create_channel("Canal Ciência", metadata={"default_blueprint_id": "bp_science"})
    payloads = {
        first["id"]: {"topic": "A queda de uma civilização esquecida", "title": "A Civilização que Desapareceu sem Explicação", "blueprint_id": "bp_history", "thumbnail_text": "DESAPARECEU", "thumbnail_status": "prompt_ready"},
        second["id"]: {"topic": "O experimento que mudou a física", "title": "O Experimento que Mudou a Física", "blueprint_id": "bp_science", "thumbnail_text": "MUDOU TUDO", "thumbnail_status": "prompt_ready"},
    }
    batch = create_batch("general", [first["id"], second["id"]], "Lote geral — um vídeo independente por canal", 1, {"channel_payloads": payloads, "topic_source": "llm"})

    tasks = create_tasks_for_batch(batch)

    assert len(tasks) == 2
    assert {task["topic"] for task in tasks} == {"A queda de uma civilização esquecida", "O experimento que mudou a física"}
    assert {task["title"] for task in tasks} == {"A Civilização que Desapareceu sem Explicação", "O Experimento que Mudou a Física"}
    assert {task["blueprint_id"] for task in tasks} == {"bp_history", "bp_science"}
    assert {task["thumbnail_text"] for task in tasks} == {"DESAPARECEU", "MUDOU TUDO"}
    assert all(task["topic_source"] == "llm" for task in tasks)
    assert all(task["creation_mode"] == "general" for task in tasks)


def test_same_channel_batch_assigns_thumbnail_variant_per_video(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import create_batch, create_channel, create_tasks_for_batch

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    channel = create_channel("Canal de thumbnails")
    variants = [
        {"concept": "Variante 1", "image_prompt": "cena 1", "overlay_text": "UM"},
        {"concept": "Variante 2", "image_prompt": "cena 2", "overlay_text": "DOIS"},
        {"concept": "Variante 3", "image_prompt": "cena 3", "overlay_text": "TRES"},
    ]
    batch = create_batch(
        "same_channel",
        [channel["id"]],
        "Tema em lote",
        3,
        {
            "channel_payloads": {
                channel["id"]: {
                    "topic": "Tema em lote",
                    "title": "Título já existente",
                    "thumbnail_variant": variants[0],
                    "thumbnail_variants": variants,
                    "thumbnail_status": "prompt_ready",
                }
            }
        },
    )

    tasks = create_tasks_for_batch(batch)

    assert [task["thumbnail_variant"]["concept"] for task in tasks] == ["Variante 1", "Variante 2", "Variante 3"]
    assert [task["thumbnail_prompt"] for task in tasks] == ["cena 1", "cena 2", "cena 3"]
    assert [task["thumbnail_text"] for task in tasks] == ["UM", "DOIS", "TRES"]


def test_general_batch_always_creates_one_task_per_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import create_batch, create_channel, create_tasks_for_batch

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    channels = [create_channel(f"Canal {index}") for index in range(3)]
    batch = create_batch("general", [channel["id"] for channel in channels], "Contexto", 99, {})

    tasks = create_tasks_for_batch(batch)

    assert len(tasks) == 3
    assert {task["channel_id"] for task in tasks} == {channel["id"] for channel in channels}
    assert all(task["topic"] == "Contexto" for task in tasks)
    assert len({task["id"] for task in tasks}) == 3


def test_update_channel_video_persists_local_override(tmp_path, monkeypatch):
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(tmp_path / "storage"))
    from hermes_ui import storage
    from hermes_ui.domain import update_channel_video

    storage.STORAGE = tmp_path / "storage"
    storage.STATE = storage.STORAGE / "state"
    storage.BLUEPRINTS = storage.STORAGE / "blueprints"
    storage.write_json("channel_videos.json", [
        {"id": "youtube_video1", "channel_id": "channel_a", "title": "Título antigo", "status": "publicado"},
        {"id": "youtube_video2", "channel_id": "channel_b", "title": "Outro canal", "status": "publicado"},
    ])

    updated = update_channel_video("youtube_video1", {"title": "Título editado", "status": "finalizado"})

    assert updated["title"] == "Título editado"
    assert updated["status"] == "finalizado"
    stored = storage.read_json("channel_videos.json", [])
    assert stored[1]["title"] == "Outro canal"
