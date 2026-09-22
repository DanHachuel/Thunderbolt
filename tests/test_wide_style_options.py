import ast
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _load_source_helpers():
    tree = ast.parse(MAIN_SOURCE)
    constant_names = {
        "WIDE_STYLE_OPTIONS",
        "VIDEO_SOURCE_VALUES",
        "VIDEO_SOURCE_LABELS",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constant_names
            for target in node.targets
        ):
            nodes.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "update":
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "channel_video_source_value",
            "channel_video_source_storage",
        }:
            nodes.append(node)
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app/main.py", "exec"), namespace)
    return namespace


def test_wide_style_options_are_exactly_the_final_five_in_order():
    namespace = _load_source_helpers()
    assert namespace["WIDE_STYLE_OPTIONS"] == [
        "Montage: Pexels/Pixabay",
        "Montage: Text-to-Images",
        "Montage: Google Imagem API",
        "Full IA: Text-to-Video",
        "Remotion",
    ]
    assert namespace["VIDEO_SOURCE_VALUES"] == {
        "Montage: Pexels/Pixabay": "pexels",
        "Montage: Text-to-Images": "text_to_images",
        "Montage: Google Imagem API": "google_images",
        "Full IA: Text-to-Video": "full_ia",
        "Remotion": "remotion",
    }


def test_video_source_aliases_normalize_to_legacy_storage_values():
    storage = _load_source_helpers()["channel_video_source_storage"]
    assert storage("pixabay") == "pexels"
    assert storage("music") == "only_music"
    assert storage("music_clip") == "music_clips"
    assert storage("clips") == "music_clips"


def test_canonical_video_source_values_are_preserved():
    storage = _load_source_helpers()["channel_video_source_storage"]
    for value in ("pexels", "text_to_images", "google_images", "full_ia", "remotion"):
        assert storage(value) == value


def test_source_alias_contract_is_explicit_in_main_source():
    for alias, canonical in (
        ("music_clip", "music_clips"),
        ("clips", "music_clips"),
        ("only_music", "only_music"),
    ):
        assert alias in MAIN_SOURCE
        assert canonical in MAIN_SOURCE
    assert '"pixabay": "Montage: Pexels/Pixabay"' in MAIN_SOURCE
    assert '"music": "Only Music"' in MAIN_SOURCE


def test_all_source_selectors_use_the_shared_options():
    assert MAIN_SOURCE.count("WIDE_STYLE_OPTIONS") >= 10
    assert "WIDE_STYLE_OPTIONS = [" in MAIN_SOURCE
    assert "Only Music\",\n    \"Clipes de Música" not in MAIN_SOURCE.split("WIDE_STYLE_OPTIONS = [", 1)[1].split("]", 1)[0]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
