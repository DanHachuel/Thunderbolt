from pathlib import Path


MAIN_SOURCE = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")


def test_web_images_reordering_disables_and_guards_both_boundaries():
    block = MAIN_SOURCE[MAIN_SOURCE.index("def render_web_images_cards("):MAIN_SOURCE.index("def render_settings(")]

    assert "is_first = index == 0" in block
    assert "is_last = index == len(cards) - 1" in block
    assert "disabled=is_first" in block
    assert "disabled=is_last" in block
    assert "and not is_first:" in block
    assert "and not is_last:" in block


def test_web_images_contains_one_guarded_swap_for_each_direction():
    block = MAIN_SOURCE[MAIN_SOURCE.index("def render_web_images_cards("):MAIN_SOURCE.index("def render_settings(")]

    assert "cards[index - 1], cards[index] = cards[index], cards[index - 1]" in block
    assert "cards[index + 1], cards[index] = cards[index], cards[index + 1]" in block
    assert block.count("cards[index - 1], cards[index] =") == 1
    assert block.count("cards[index + 1], cards[index] =") == 1
