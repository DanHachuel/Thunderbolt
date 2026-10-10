"""UI e composições Remotion (0.9.79) — um dropdown, uma lista, um conceito.

- o modo Remotion tem UM dropdown de Blueprint com a lista completa;
- a aba Blueprints Youtube mostra todos os blueprints (sem filtros de tipo);
- as 5 composições continuam registadas em Root.tsx com calculateMetadata
  fiel ao layout real dos componentes;
- list_blueprints inclui os 5 Remotion como qualquer outro blueprint.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
ROOT_TSX = (ROOT / "packages" / "remotion" / "src" / "Root.tsx").read_text(encoding="utf-8")

REMOTION_BLUEPRINTS = (
    "Blueprint Remotion - Quiz Videos",
    "Blueprint Remotion - Social Media Reels",
    "Blueprint Remotion - Top 10 Ranking Videos",
    "Blueprint Remotion - Would You Rather",
    "Blueprint Remotion - Inspirational Long-Form Videos",
)


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


def test_remotion_ui_has_single_dropdown():
    """UM dropdown de blueprint no modo Remotion — só um, com a lista completa."""
    form_block = APP_SOURCE.split("def render_video_generation_settings(", 1)[1]
    assert 'settings["video_source"] == "Remotion"' in form_block
    # o dropdown único usa list_blueprints() — a lista completa
    assert "list_blueprints()" in form_block
    assert 'key=f"{prefix}_remotion_blueprint"' in form_block
    assert 'settings["blueprint_id"] = selected_blueprint_id' in form_block
    # não existe segundo dropdown, nem formato, nem personalidade
    assert '"Formato Remotion"' not in form_block
    assert "remotion_format_id" not in form_block
    assert "remotion_personality_id" not in form_block
    assert "list_personality_blueprints" not in form_block
    assert "list_remotion_formats" not in form_block


def test_blueprints_youtube_tab_shows_all():
    """A aba mostra todos os blueprints — usa list_blueprint_files() sem
    filtros de tipo; os Remotion (json em importados) passam nas exclusões
    (que só removem ficheiros de controlo e pastas de outras abas)."""
    render_block = APP_SOURCE.split("def render_blueprints():", 1)[1].split("def render_music_blueprints():", 1)[0]
    assert "list_blueprint_files()" in render_block
    assert "Blueprints de conteúdo" not in render_block
    # a lista única tem a contagem total (json + md)
    assert 'st.subheader(f"Blueprints ({total})")' in render_block

    from hermes_ui import storage

    # os 5 Remotion não são filtrados pelo catálogo (só control files/pastas)
    for name in REMOTION_BLUEPRINTS:
        assert storage._is_selectable_blueprint(storage.BLUEPRINTS / "importados" / f"{name}.json")


def test_list_blueprints_includes_all_five_remotion(tmp_path, monkeypatch):
    from hermes_ui import blueprint_loader, storage

    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(blueprint_loader, "BLUEPRINTS_DIR", root / "blueprints")
    (root / "blueprints" / "importados").mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)

    listed = {item["id"] for item in blueprint_loader.list_blueprints()}
    assert set(REMOTION_BLUEPRINTS) <= listed


def test_seed_blueprints_directory_has_the_five_remotion():
    for name in REMOTION_BLUEPRINTS:
        assert (ROOT / "seed" / "blueprints" / f"{name}.json").is_file(), name
    # a pasta separada de schemas deixou de existir — um sítio só
    assert not (ROOT / "packages" / "remotion" / "schemas").exists()
