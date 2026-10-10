"""UI e composições Remotion (0.9.76): personalidade + formato.

- no modo Remotion o formulário mostra DOIS dropdowns: Blueprint de
  personalidade (MILITAR, FINANCE USA, …) e Formato Remotion (quiz,
  social_reel, top_10, would_you_rather, inspirational);
- as 5 composições estão registadas em Root.tsx com calculateMetadata fiel ao
  layout real dos componentes;
- list_remotion_formats devolve os 5 formatos de packages/remotion/schemas/.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
ROOT_TSX = (ROOT / "packages" / "remotion" / "src" / "Root.tsx").read_text(encoding="utf-8")


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


def test_ui_remotion_mode_shows_personality_and_format_dropdowns():
    form_block = APP_SOURCE.split("def render_video_generation_settings(", 1)[1]
    assert 'settings["video_source"] == "Remotion"' in form_block
    # dropdown 1: personalidade
    assert "list_personality_blueprints()" in form_block
    assert '"Blueprint (personalidade do canal)"' in form_block
    assert 'settings["remotion_personality_id"] = selected_personality_id' in form_block
    # dropdown 2: formato
    assert "list_remotion_formats()" in form_block
    assert '"Formato Remotion"' in form_block
    assert 'settings["remotion_format_id"] = selected_format_id' in form_block
    # placeholders dinâmicos do formato
    assert "find_placeholders" in form_block
    assert 'settings["blueprint_values"]' in form_block


def test_list_remotion_formats_returns_the_five_formats():
    from hermes_ui.blueprint_loader import list_remotion_formats

    formats = list_remotion_formats()
    assert sorted(item["format_id"] for item in formats) == [
        "inspirational",
        "quiz",
        "social_reel",
        "top_10",
        "would_you_rather",
    ]
    compositions = {item["format_id"]: item["composition_id"] for item in formats}
    assert compositions["quiz"] == "Quiz"
    assert compositions["top_10"] == "Top10"
    assert compositions["social_reel"] == "SocialReel"
    assert compositions["would_you_rather"] == "WouldYouRather"
    assert compositions["inspirational"] == "InspirationalVideo"


def test_list_personality_blueprints_excludes_formats(tmp_path, monkeypatch):
    from hermes_ui import blueprint_loader, storage

    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(blueprint_loader, "BLUEPRINTS_DIR", root / "blueprints")
    importados = root / "blueprints" / "importados"
    importados.mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (importados / "MILITAR.json").write_text('{"id": "militar", "name": "Canal Militar"}', encoding="utf-8")
    (importados / "FINANCE USA.json").write_text('{"id": "finance-usa", "name": "FINANCE USA"}', encoding="utf-8")
    (importados / "quiz-fmt.json").write_text('{"format_id": "quiz", "composition_id": "Quiz"}', encoding="utf-8")

    ids = {item["id"] for item in blueprint_loader.list_personality_blueprints()}
    assert {"militar", "finance-usa"} <= ids
    assert "quiz" not in ids


def test_schemas_directory_ships_the_five_formats():
    schemas_dir = ROOT / "packages" / "remotion" / "schemas"
    assert sorted(path.name for path in schemas_dir.glob("*.schema.json")) == [
        "inspirational.schema.json",
        "quiz.schema.json",
        "social_reel.schema.json",
        "top_10.schema.json",
        "would_you_rather.schema.json",
    ]
