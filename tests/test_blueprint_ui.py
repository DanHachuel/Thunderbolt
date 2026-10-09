"""UI e composições Remotion dos Blueprints (0.9.75).

- o seletor de blueprints aparece no formulário quando a Fonte do Vídeo é
  "Remotion", com placeholders dinâmicos (spec: Implementação dos Blueprints
  Remotion no Thunderbolt, Tarefa D);
- as 5 composições estão registadas em Root.tsx com calculateMetadata (Tarefa A);
- list_blueprints/find_placeholders expõem os 5 seeds (Tarefa E.3).
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
ROOT_TSX = (ROOT / "packages" / "remotion" / "src" / "Root.tsx").read_text(encoding="utf-8")
SEED_BLUEPRINTS = ROOT / "seed" / "blueprints"


def test_root_tsx_registers_all_seven_compositions():
    for composition_id in (
        "LongFormVideo",
        "ShortVideo",
        "InspirationalVideo",
        "Quiz",
        "SocialReel",
        "Top10",
        "WouldYouRather",
    ):
        assert f'id="{composition_id}"' in ROOT_TSX, composition_id
    assert ROOT_TSX.count("calculateMetadata") >= 7


def test_root_tsx_metadata_mirrors_component_layouts():
    # Intro/outro fixos de 90 frames do Quiz e WouldYouRather têm de constar
    # no calculateMetadata — estimativas de texto cortariam o áudio real.
    def _normalise(block: str) -> str:
        return " ".join(block.split())

    quiz_block = _normalise(ROOT_TSX.split("const quizFrames", 1)[1][:900])
    assert "90 +" in quiz_block and "+ 90" in quiz_block
    wyr_block = _normalise(ROOT_TSX.split("const wouldYouRatherFrames", 1)[1][:900])
    assert "90 +" in wyr_block and "+ 90" in wyr_block
    assert (ROOT / "packages" / "remotion" / "src" / "utils.ts").is_file()


def test_all_five_composition_components_exist():
    for component in ("InspirationalVideo", "Quiz", "SocialReel", "Top10", "WouldYouRather"):
        assert (ROOT / "packages" / "remotion" / "src" / "compositions" / f"{component}.tsx").is_file(), component


def test_ui_has_blueprint_selector_for_remotion_source():
    form_block = APP_SOURCE.split("def render_video_generation_settings(", 1)[1]
    assert 'settings["video_source"] == "Remotion"' in form_block
    assert "list_blueprints()" in form_block
    assert "find_placeholders" in form_block
    assert 'settings["blueprint_id"] = selected_blueprint_id' in form_block
    assert 'settings["blueprint_values"]' in form_block


def test_list_blueprints_returns_the_five_seeds(tmp_path, monkeypatch):
    from hermes_ui import blueprint_loader

    storage_blueprints = tmp_path / "blueprints"
    (storage_blueprints / "importados").mkdir(parents=True)
    for path in sorted(SEED_BLUEPRINTS.glob("*.json")):
        if path.name == "thumbnail_blueprint_pairs.json":
            continue
        shutil.copy2(path, storage_blueprints / "importados" / path.name)

    monkeypatch.setattr(blueprint_loader, "BLUEPRINTS_DIR", storage_blueprints)
    listed = blueprint_loader.list_blueprints()
    assert {item["blueprint_id"] for item in listed} == {
        "inspirational_long_form",
        "quiz_videos",
        "social_media_reels",
        "top_10_videos",
        "would_you_rather",
    }


def test_list_blueprints_ignores_classic_channel_blueprints(tmp_path, monkeypatch):
    """Blueprints de canal clássicos (sem blueprint_id) não entram no seletor."""
    from hermes_ui import blueprint_loader

    storage_blueprints = tmp_path / "blueprints"
    (storage_blueprints / "importados").mkdir(parents=True)
    (storage_blueprints / "importados" / "FINANCE USA.json").write_text('{"id": "finance-usa", "name": "FINANCE USA"}', encoding="utf-8")
    shutil.copy2(SEED_BLUEPRINTS / "Blueprint Remotion - Quiz Videos.json", storage_blueprints / "importados" / "Blueprint Remotion - Quiz Videos.json")

    monkeypatch.setattr(blueprint_loader, "BLUEPRINTS_DIR", storage_blueprints)
    listed = blueprint_loader.list_blueprints()
    assert [item["blueprint_id"] for item in listed] == ["quiz_videos"]


def test_find_placeholders_returns_all():
    from hermes_ui.blueprint_loader import find_placeholders, load_blueprint

    placeholders = find_placeholders(load_blueprint("quiz_videos"))
    assert {"language", "difficulty"} <= set(placeholders)
