"""Music Thumbnail Blueprints — separação de vídeo vs. música.

Trava a fronteira: os Music Thumbnail Blueprints vivem numa pasta exclusiva
(seed/blueprints/music_thumbnails/ -> BLUEPRINTS/music_thumbnails/), o catálogo
de VÍDEO nunca os vê, o catálogo de música só os vê, o pipeline "Clipes de
Música" gera o fundo SEM texto e queima o headline por cima (PIL), e o campo
chega à tarefa. Nada de blueprint de música aparece no pipeline de vídeo normal.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import hermes_ui.thumbnail_blueprints as tb
import hermes_ui.music_clips as music_clips
from hermes_ui.blueprint_loader import _blueprint_files  # catálogo de conteúdo/Remotion
from hermes_ui.creative_generation import CreativeGenerationError

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
WORKER = (ROOT / "hermes_ui" / "pipeline_worker.py").read_text(encoding="utf-8")

HEROES = "MUSIC-ANIME-HEROES_Thumbnail_Blueprint"
GIRLS = "MUSIC-ANIME-GIRLS_Thumbnail_Blueprint"

# O seed real (enviado pelo utilizador) tem os dois blueprints.
SEED_MUSIC = ROOT / "seed" / "blueprints" / "music_thumbnails"


def _isolated_music(monkeypatch, tmp_path):
    """Aponta o loader de música e o loader de vídeo para pastas tmp distintas."""
    music_storage = tmp_path / "storage_music"
    music_seed = tmp_path / "seed_music"
    # o catálogo de vídeo lê BLUEPRINTS/"thumbnails" — com BLUEPRINTS apontado a
    # tmp_path, a pasta de vídeo fica em tmp_path/thumbnails (separada da música).
    video_thumbs = tmp_path / "thumbnails"
    for folder in (music_storage, music_seed, video_thumbs):
        folder.mkdir(parents=True, exist_ok=True)
    (music_seed / f"{HEROES}.md").write_text("# RisingWave\n- dark, intense, neon\n", encoding="utf-8")
    (music_seed / f"{GIRLS}.md").write_text("# ShakeMusic\n- dark, moody, neon\n", encoding="utf-8")
    (video_thumbs / "FINANCE_Thumbnail_Blueprint.md").write_text("# Finance\n", encoding="utf-8")
    monkeypatch.setattr(tb, "MUSIC_THUMBNAIL_BLUEPRINTS", music_storage)
    monkeypatch.setattr(tb, "SEED_MUSIC_THUMBNAIL_BLUEPRINTS", music_seed)
    monkeypatch.setattr(tb, "BLUEPRINTS", tmp_path)  # thumbnails de vídeo, isolado
    return {"music": music_storage, "video": video_thumbs}


# ── 1. o catálogo de música só lista a pasta music_thumbnails ──────────────────


def test_music_catalog_lists_only_the_music_blueprints(monkeypatch, tmp_path):
    paths = _isolated_music(monkeypatch, tmp_path)
    catalog = [identifier for identifier, _label in tb.list_music_thumbnail_blueprints()]
    assert set(catalog) == {HEROES, GIRLS}
    assert "FINANCE_Thumbnail_Blueprint" not in catalog


def test_video_catalog_never_sees_the_music_blueprints(monkeypatch, tmp_path):
    _isolated_music(monkeypatch, tmp_path)
    # o catálogo de vídeo aponta para a pasta de thumbnails de vídeo isolada
    video = [identifier for identifier, _label in tb.thumbnail_blueprint_catalog()]
    assert "FINANCE_Thumbnail_Blueprint" in video
    for music_id in (HEROES, GIRLS):
        assert music_id not in video
        assert tb.resolve_thumbnail_blueprint(music_id).get("content") in ("", None)


def test_content_and_remotion_catalog_excludes_the_music_folder(monkeypatch, tmp_path):
    _isolated_music(monkeypatch, tmp_path)
    names = {p.name for p in _blueprint_files()}
    for music_id in (HEROES, GIRLS):
        assert f"{music_id}.md" not in names


# ── 2. resolver + precedência tarefa > canal ──────────────────────────────────


def test_resolve_music_thumbnail_blueprint_reads_only_this_folder(monkeypatch, tmp_path):
    _isolated_music(monkeypatch, tmp_path)
    resolved = tb.resolve_music_thumbnail_blueprint(HEROES)
    assert resolved["id"] == HEROES
    assert "RisingWave" in resolved["content"]
    assert tb.resolve_music_thumbnail_blueprint("") == {}
    assert tb.resolve_music_thumbnail_blueprint("NAO_EXISTE").get("content") in ("", None)


def test_music_blueprint_for_task_prefers_task_then_channel_default(monkeypatch, tmp_path):
    _isolated_music(monkeypatch, tmp_path)
    # selecção explícita da tarefa vence
    picked = tb.music_thumbnail_blueprint_for_task({}, {"music_thumbnail_blueprint_id": HEROES})
    assert picked["content"]
    # default do canal como pré-preenchimento
    from_channel = tb.music_thumbnail_blueprint_for_task({"default_music_thumbnail_blueprint_id": GIRLS}, {})
    assert "ShakeMusic" in from_channel["content"]
    # tarefa vence o canal
    both = tb.music_thumbnail_blueprint_for_task({"default_music_thumbnail_blueprint_id": GIRLS}, {"music_thumbnail_blueprint_id": HEROES})
    assert "RisingWave" in both["content"]
    # sem nada → vazio (sem fallback genérico, diferente do thumbnail de vídeo)
    assert tb.music_thumbnail_blueprint_for_task({}, {}).get("content") in ("", None)


# ── 3. a imagem é gerada SEM texto; o headline é queimado por cima (PIL) ───────


def test_apply_music_text_overlay_burns_on_top_and_keeps_a_jpeg(tmp_path):
    from PIL import Image

    background = tmp_path / "bg.jpg"
    Image.new("RGB", (640, 360), (12, 12, 18)).save(background, "JPEG")
    burned = music_clips.apply_music_text_overlay(background, "God Mode Music Enter Your Villain Era")
    assert burned.is_file() and burned.name == "bg-texto.jpg"
    with Image.open(burned) as handle:
        assert handle.format == "JPEG"
        assert handle.size == (640, 360)


def test_apply_music_text_overlay_returns_original_without_a_headline(tmp_path):
    from PIL import Image

    background = tmp_path / "bg.jpg"
    Image.new("RGB", (320, 180), (0, 0, 0)).save(background, "JPEG")
    assert music_clips.apply_music_text_overlay(background, "   ") == background


def test_headline_lines_split_at_two_lines():
    assert music_clips._headline_lines("God Mode Music") == ["God Mode Music"]
    # até 2 linhas: gancho (≤5 palavras) + contexto (≤4), como rege o blueprint
    assert music_clips._headline_lines("God Mode Music enter your villain era now") == ["God Mode Music enter your", "villain era now"]


# ── 4. o clip exige o blueprint selecionado (antes de tocar em qualquer provider)


def test_generate_music_clip_frame_requires_a_music_blueprint(monkeypatch):
    monkeypatch.setattr(tb, "MUSIC_THUMBNAIL_BLUEPRINTS", Path(__file__).parent)
    monkeypatch.setattr(tb, "SEED_MUSIC_THUMBNAIL_BLUEPRINTS", Path(__file__).parent)
    with pytest.raises(CreativeGenerationError):
        music_clips.generate_music_clip_frame({"topic": "Song"}, {}, {})


# ── 5. UI + pipeline: placeholder substituído, campo obrigatório ───────────────


def test_ui_exposes_the_music_thumbnail_blueprint_dropdown_and_requirement():
    assert "list_music_thumbnail_blueprints" in MAIN
    assert "Music Thumbnail Blueprint" in MAIN
    assert "Clipes de Música exige um Music Thumbnail Blueprint selecionado." in MAIN
    assert 'UNAVAILABLE_VIDEO_SOURCES = set()' in MAIN
    assert 'if style in {"only_music", "music_clips"}:' in MAIN


def test_pipeline_worker_ships_the_music_clips_route():
    assert "from hermes_ui.music_clips import run_music_clip_task" in WORKER
    assert "run_music_clip_task(_task_by_id(task_id) or task, settings, channel)" in WORKER
    assert "placeholder e não está disponível" not in WORKER


# ── 6. o campo chega à tarefa (criação e remake) ──────────────────────────────


def _isolate_storage(tmp_path, monkeypatch):
    import hermes_ui.storage as storage

    monkeypatch.setattr(storage, "STORAGE", tmp_path)
    monkeypatch.setattr(storage, "STATE", tmp_path / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", tmp_path / "blueprints")
    monkeypatch.setattr(storage, "MUSIC_THUMBNAIL_BLUEPRINTS", tmp_path / "blueprints" / "music_thumbnails")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "blueprints").mkdir(parents=True, exist_ok=True)
    (tmp_path / "blueprints" / "music_thumbnails").mkdir(parents=True, exist_ok=True)


def test_created_music_clip_task_carries_the_music_thumbnail_blueprint_id(tmp_path, monkeypatch):
    import hermes_ui.domain as domain
    import hermes_ui.storage as storage

    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("channels.json", [{
        "id": "ch", "name": "Canal", "platform": "youtube", "style_wide": "music_clips",
        "language": "Português",
    }])
    batch = domain.create_batch(
        "single", ["ch"], "God Mode", 1,
        {"automation_worker": False, "style_wide": "music_clips", "generation_settings": {"music_thumbnail_blueprint_id": HEROES}},
    )
    tasks = domain.create_tasks_for_batch(batch)
    assert tasks, "a tarefa de clip tinha de ser criada"
    assert tasks[0]["music_thumbnail_blueprint_id"] == HEROES
    assert tasks[0]["generation_settings"]["music_thumbnail_blueprint_id"] == HEROES


def test_channel_default_music_thumbnail_blueprint_prefills_the_task(tmp_path, monkeypatch):
    import hermes_ui.domain as domain
    import hermes_ui.storage as storage

    _isolate_storage(tmp_path, monkeypatch)
    storage.write_json("channels.json", [{
        "id": "ch", "name": "Canal", "platform": "youtube", "style_wide": "music_clips",
        "language": "Português", "default_music_thumbnail_blueprint_id": GIRLS,
    }])
    batch = domain.create_batch("single", ["ch"], "Song", 1, {"style_wide": "music_clips", "generation_settings": {}})
    tasks = domain.create_tasks_for_batch(batch)
    assert tasks[0]["music_thumbnail_blueprint_id"] == GIRLS


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))