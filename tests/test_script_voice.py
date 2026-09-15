from hermes_ui.script_voice import narration_text_from_script
from hermes_ui.pipeline_worker import _moneyprinter_cli_args


def test_narration_filters_title_summary_headings_and_visual_block():
    script = """> Russia's Submarines Are Hiding Inside Civilian Cargo Ships — Here's How
> An operational breakdown of disguised patrols.
# Russia's Submarines Are Hiding Inside Civilian Cargo Ships — Here's How
---
## HOOK (0:00 – 0:35)
**[VISUAL]**
Cold-open aerial drone shot: a rust-streaked bulk carrier cuts through grey North Atlantic swells.
**[NARRAÇÃO]**
Russia is using a deceptive maritime pattern to conceal its patrols.
"""

    result = narration_text_from_script(script)

    assert result == "Russia is using a deceptive maritime pattern to conceal its patrols."
    assert "Hashatag" not in result
    assert "VISUAL" not in result
    assert "Cold-open" not in result
    assert "0:00" not in result


def test_narration_without_explicit_voice_keeps_prose_but_not_editorial_labels():
    script = """# The Arctic Route
## INTRO (0:00 - 0:20)
The convoy moves through freezing water.
**[VISUAL]**
Satellite imagery shows the coastline.
The narrator explains the strategic risk.
"""

    result = narration_text_from_script(script)

    assert result == "The convoy moves through freezing water."
    assert "Satellite" not in result
    assert "narrator explains" not in result


def test_narration_strips_inline_markdown():
    assert narration_text_from_script("**This** is a [spoken](https://example.com) line.") == "This is a spoken line."


def test_moneyprinter_cli_receives_clean_narration_text():
    script = """# Title
**[VISUAL]**
Ships move through the fog.
**[NARRAÇÃO]**
The patrol follows a concealed route.
"""
    args = _moneyprinter_cli_args({"video_script": script, "generation_settings": {}}, "pexels", {})
    assert args[args.index("--video-script") + 1] == "The patrol follows a concealed route."
