from pathlib import Path

from hermes_ui.channel_import import normalize_channel_row
from hermes_ui.only_music import resolve_music_source
from hermes_ui.text_to_images import split_script_into_scenes


def test_channel_source_aliases_are_canonical():
    assert normalize_channel_row({"name": "Canal", "style_wide": "Montage: Text-to-Images"})["style_wide"] == "text_to_images"
    assert normalize_channel_row({"name": "Canal", "style_wide": "Only Music"})["style_wide"] == "only_music"
    assert normalize_channel_row({"name": "Canal", "style_wide": "Clipes de Música"})["style_wide"] == "music_clips"


def test_split_script_uses_timestamps_when_available():
    scenes = split_script_into_scenes(
        "um dois três quatro",
        [{"word": "um", "start": 0, "end": 1}, {"word": "dois", "start": 1, "end": 2.2}, {"word": "três", "start": 2.2, "end": 4}, {"word": "quatro", "start": 4, "end": 5.5}],
        target_seconds=2,
    )
    assert scenes
    assert scenes[0]["duration"] >= 2
    assert scenes[-1]["text"].endswith("quatro")


def test_split_script_has_deterministic_word_count_fallback():
    scenes = split_script_into_scenes(" ".join(["palavra"] * 30), target_seconds=5, wpm=60)
    assert len(scenes) == 6
    assert all(scene["prompt"] if "prompt" in scene else True for scene in scenes)


def test_only_music_resolves_explicit_existing_file(tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"audio")
    assert resolve_music_source({"music_path": str(audio)}) == audio


def test_only_music_does_not_resolve_missing_file(tmp_path):
    assert resolve_music_source({"music_path": str(tmp_path / "missing.mp3")}) is None
