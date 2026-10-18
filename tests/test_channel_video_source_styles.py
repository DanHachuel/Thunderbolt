"""Testes dos estilos dependentes da Fonte do vídeo (1.0.06).

O campo "Estilo" das Configurações de vídeo do canal só mostra as opções
válidas da fonte escolhida (VIDEO_SOURCE_STYLES); fontes de stock/web ocultam
o campo; canais antigos são migrados para os rótulos canónicos de 14 estilos.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
DOMAIN_SOURCE = (ROOT / "hermes_ui" / "domain.py").read_text(encoding="utf-8")
STORAGE_SOURCE = (ROOT / "hermes_ui" / "storage.py").read_text(encoding="utf-8")


def _app_main():
    from app import main as app_main

    return app_main


def _constant(name: str):
    # AI_STYLE_OPTIONS/REMOTION_STYLE_OPTIONS são literais puros; o
    # VIDEO_SOURCE_STYLES referencia-os por nome, por isso usa-se o módulo.
    return getattr(_app_main(), name)


def _isolate_storage(tmp_path: Path, monkeypatch) -> None:
    from hermes_ui import storage

    root = tmp_path / "storage"
    monkeypatch.setenv("THUNDERBOLT_STORAGE_DIR", str(root))
    storage.STORAGE = root
    storage.STATE = root / "state"
    storage.BLUEPRINTS = root / "blueprints"
    storage.STATE.mkdir(parents=True, exist_ok=True)


# ── Mapeamento Fonte → Estilos ────────────────────────────────────────────────


def test_video_source_styles_mapping_matches_business_rules():
    styles = _constant("VIDEO_SOURCE_STYLES")
    ai_options = _constant("AI_STYLE_OPTIONS")
    assert styles["Montage: Pexels/Pixabay"] == []
    assert styles["Montage: Text-to-Images"] == ai_options
    assert styles["Montage: Web Images"] == []
    assert styles["Full IA: Text-to-Video"] == ai_options
    assert styles["Only Music"] == ai_options
    assert styles["Clipes de Música"] == ai_options
    assert styles["Remotion"] == _constant("REMOTION_STYLE_OPTIONS")
    # Todas as fontes de WIDE_STYLE_OPTIONS têm entrada no dicionário.
    for label in _constant("WIDE_STYLE_OPTIONS"):
        assert label in styles


def test_ai_style_options_are_canonical_14():
    assert _constant("AI_STYLE_OPTIONS") == [
        "Natural", "Ultra Realista", "Cartoon", "Stickman Cartoon", "Retro 90s Cartoon",
        "Wool sculpture miniatures", "LEGO Style", "Paper cutout style", "Anime Style",
        "Studio Ghibli Style", "Stop Motion Style (Massinha)", "Ukiyo Style",
        "Pixel Animation", "Pixar Style",
    ]
    # Rótulos antigos saíram da lista canónica (têm migração própria).
    assert "Natural Realista" not in _constant("AI_STYLE_OPTIONS")
    assert "Cocomelon style" not in _constant("AI_STYLE_OPTIONS")


def test_remotion_style_options_start_with_free_default_and_known_skills():
    remotion = _constant("REMOTION_STYLE_OPTIONS")
    assert remotion[0] == "Sem Estilo/Livre"
    assert "Vox-style Motion" in remotion
    assert "Hand-drawn Canvas Animation" in remotion


# ── UI do card do canal ──────────────────────────────────────────────────────


def _channel_card_block() -> str:
    return MAIN_SOURCE[MAIN_SOURCE.index("def render_channel_video_defaults("):MAIN_SOURCE.index("def render_channel_edit_form(")]


def test_channel_card_style_selectbox_is_conditional_on_selected_source():
    card = _channel_card_block()
    # A fonte normalizada escolhe a lista; o campo só existe quando há estilos.
    assert "source_key = channel_video_source_value(selected_source)" in card
    assert "style_options = VIDEO_SOURCE_STYLES.get(source_key, [])" in card
    assert 'selected_style = st.selectbox(\n                    "Estilo",' in card
    # Fontes sem estilos ocultam o campo com uma legenda explicativa.
    assert 'st.caption("Esta fonte de vídeo não utiliza estilos de IA.")' in card
    # Reset + aviso quando o estilo gravado não serve para a nova fonte.
    assert 'st.session_state.pop(style_widget_key, None)' in card
    assert 'st.info("O estilo foi redefinido porque a fonte de vídeo mudou.")' in card
    # Key estável por canal, valor gravado preservado quando ainda é válido.
    assert 'style_widget_key = f"channel_style_{channel_id}"' in card
    assert "index=style_options.index(stored_style) if stored_style in style_options else 0" in card


def test_channel_style_save_persists_default_and_alias_keys():
    card = _channel_card_block()
    assert '"default_style_ia": str(selected_style or "")' in card
    assert '"style_ia": str(selected_style or "")' in card
    # A automação já lê o alias style_ia (automation_worker).
    automation = (ROOT / "hermes_ui" / "automation_worker.py").read_text(encoding="utf-8")
    assert '"style_ia": channel.get("style_ia") or ""' in automation


# ── Migração de canais existentes ─────────────────────────────────────────────


def test_migrate_channel_style_values_converts_legacy_labels(tmp_path, monkeypatch):
    from hermes_ui import storage

    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("channels.json", [
        {"id": "channel-1", "name": "A", "style_ia": "Natural Realista", "default_style_ia": ""},
        {"id": "channel-2", "name": "B", "style_ia": "Cocomelon style", "default_style_ia": "Cocomelon style"},
        {"id": "channel-3", "name": "C", "style_ia": "Pixar Style"},
        {"id": "channel-4", "name": "D"},
    ])
    storage._ensured_storage_root = None

    storage.ensure_storage()

    channels = {item["id"]: item for item in storage.read_json("channels.json", [])}
    assert channels["channel-1"]["style_ia"] == "Natural"
    assert channels["channel-2"]["style_ia"] == "Cartoon"
    assert channels["channel-2"]["default_style_ia"] == "Cartoon"
    # Estilos já canónicos e canais sem estilo ficam intactos.
    assert channels["channel-3"]["style_ia"] == "Pixar Style"
    assert "style_ia" not in channels["channel-4"]


def test_migrate_channel_style_values_is_idempotent(tmp_path, monkeypatch):
    from hermes_ui import storage

    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("channels.json", [{"id": "channel-1", "style_ia": "Natural Realista"}])
    storage._ensured_storage_root = None
    storage.ensure_storage()
    first = storage.read_json("channels.json", [])
    assert first[0]["style_ia"] == "Natural"

    # Segunda passada: ficheiro já migrado não é reescrito nem corrompido.
    storage._ensured_storage_root = None
    storage.ensure_storage()
    second = storage.read_json("channels.json", [])
    assert second[0]["style_ia"] == "Natural"


def test_migrate_channel_style_values_survives_missing_or_corrupt_file(tmp_path, monkeypatch):
    from hermes_ui import storage

    _isolate_storage(tmp_path, monkeypatch)
    (storage.STATE / "channels.json").write_text("não é json", encoding="utf-8")
    # A migração é tolerante: ficheiro inválido → no-op seguro, nunca lança.
    storage.migrate_channel_style_values()
    assert (storage.STATE / "channels.json").read_text(encoding="utf-8") == "não é json"
    # Sem ficheiro: também no-op (não cria channels.json).
    (storage.STATE / "channels.json").unlink()
    storage.migrate_channel_style_values()
    assert not (storage.STATE / "channels.json").exists()


# ── Backend: defaults do canal chegam às tarefas ──────────────────────────────


def _channel_with_style(tmp_path, monkeypatch, style: str, legacy_alias: str = "") -> None:
    from hermes_ui import storage

    _isolate_storage(tmp_path, monkeypatch)
    record = {
        "id": "channel-styled",
        "name": "Canal com estilo",
        "platform": "youtube",
        "style_wide": "text_to_images",
        "default_style_ia": style,
    }
    if legacy_alias:
        record["style_ia"] = legacy_alias
    storage.write_json("channels.json", [record])
    storage.write_json("tasks.json", [])
    storage.write_json("batches.json", [])
    storage.write_json("queues.json", {"niche": [], "blueprint": [], "brand": [], "script": [], "title": [], "thumbnail": [], "video": [], "edit": [], "upload": []})


def test_create_tasks_for_channel_uses_channel_style_when_defined(tmp_path, monkeypatch):
    _channel_with_style(tmp_path, monkeypatch, style="Anime Style", legacy_alias="Anime Style")
    from hermes_ui.domain import create_batch, create_tasks_for_batch

    batch = create_batch("single", ["channel-styled"], "Tema", 1, {"automation_worker": True, "style_wide": "text_to_images"})
    tasks = create_tasks_for_batch(batch)
    settings = tasks[0]["generation_settings"]
    assert settings["style_ia"] == "Anime Style"
    assert settings["text_to_images_style"] == "Anime Style"
    assert tasks[0]["style_ia"] == "Anime Style"


def test_create_tasks_explicit_form_style_wins_over_channel_default(tmp_path, monkeypatch):
    _channel_with_style(tmp_path, monkeypatch, style="Anime Style")
    from hermes_ui.domain import create_batch, create_tasks_for_batch

    options = {"generation_settings": {"text_to_images_style": "Pixar Style", "style_ia": ""}}
    batch = create_batch("single", ["channel-styled"], "Tema", 1, options)
    tasks = create_tasks_for_batch(batch)
    settings = tasks[0]["generation_settings"]
    # A escolha explícita do formulário de criação prevalece sobre o default.
    assert settings["text_to_images_style"] == "Pixar Style"


def test_create_tasks_without_channel_style_keep_settings_untouched(tmp_path, monkeypatch):
    _channel_with_style(tmp_path, monkeypatch, style="")
    from hermes_ui.domain import create_batch, create_tasks_for_batch

    batch = create_batch("single", ["channel-styled"], "Tema", 1, {"generation_settings": {"text_to_images_style": "Ukiyo Style"}})
    tasks = create_tasks_for_batch(batch)
    settings = tasks[0]["generation_settings"]
    # Canal sem estilo definido não injecta chaves nem sobrescreve a escolha.
    assert settings["text_to_images_style"] == "Ukiyo Style"
    assert settings.get("style_ia", "") == ""


def test_remake_refresh_applies_current_channel_style(tmp_path, monkeypatch):
    _channel_with_style(tmp_path, monkeypatch, style="LEGO Style")
    from hermes_ui.domain import _refresh_task_channel_video_settings

    task = {
        "channel_id": "channel-styled",
        "generation_settings": {"text_to_images_style": "Anime Style", "style_ia": "Anime Style"},
    }
    _refresh_task_channel_video_settings(task)
    # O remake revalida o contexto que o canal controla — estilo incluído.
    assert task["generation_settings"]["text_to_images_style"] == "LEGO Style"
    assert task["generation_settings"]["style_ia"] == "LEGO Style"


def test_remake_without_channel_style_keeps_task_choice(tmp_path, monkeypatch):
    _channel_with_style(tmp_path, monkeypatch, style="")
    from hermes_ui.domain import _refresh_task_channel_video_settings

    task = {
        "channel_id": "channel-styled",
        "generation_settings": {"text_to_images_style": "Anime Style"},
    }
    _refresh_task_channel_video_settings(task)
    # Sem estilo no canal, a escolha original da tarefa sobrevive ao remake.
    assert task["generation_settings"]["text_to_images_style"] == "Anime Style"


# ── Integração da migração no arranque ────────────────────────────────────────


def test_migrate_channel_style_values_is_wired_into_ensure_storage():
    assert "migrate_channel_style_values()" in STORAGE_SOURCE
    assert "def migrate_channel_style_values() -> None:" in STORAGE_SOURCE
    assert '"Natural Realista": "Natural"' in STORAGE_SOURCE
    assert '"Cocomelon style": "Cartoon"' in STORAGE_SOURCE
    assert 'channel_generation_defaults["text_to_images_style"] = channel_style' in DOMAIN_SOURCE
    assert 'generation_settings["text_to_images_style"] = channel_style' in DOMAIN_SOURCE
