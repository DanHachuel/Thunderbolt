import ast
from pathlib import Path


def _main_module():
    return ast.parse(Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8"))


def _constant(name):
    assignment = next(node for node in _main_module().body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
    return ast.literal_eval(assignment.value)


def test_ai_style_options_are_complete_and_ordered():
    assert _constant("AI_STYLE_OPTIONS") == [
        "Natural Realista", "Cocomelon style", "Retro 90s Cartoon", "Wool sculpture miniatures",
        "LEGO Style", "Paper cutout style", "Anime Style", "Studio Ghibli Style",
        "Stop Motion Style (Massinha)", "Ukiyo Style", "Pixel Animation", "Pixar Style",
    ]


def test_wide_style_labels_and_music_background_rule_are_present():
    options = _constant("WIDE_STYLE_OPTIONS")
    # Desde a332304 ("prioritized web image scraping providers") a opção Google
    # Imagem API passou a ser o pool genérico "Montage: Web Images". Este teste
    # verifica presença das etiquetas e da regra de fundo musical; a ordem exata
    # da lista fica verificada em test_wide_style_options.py.
    assert "Montage: Pexels/Pixabay" in options
    assert "Montage: Text-to-Images" in options
    assert "Montage: Web Images" in options
    assert "Full IA: Text-to-Video" in options
    assert "Remotion" in options
    assert "Only Music" in Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    # A regra cobre os modos musicais actuais (only_music e music_clips);
    # full_ia usa fundo de IA e os restantes usam stock.
    assert '"background_mode": "none" if style in {"only_music", "music_clips"} else ("ai" if style == "full_ia" else "stock")' in source
    assert 'st.selectbox("Estilo IA", AI_STYLE_OPTIONS' in source


def test_video_creation_has_ai_topic_blueprint_and_creative_controls():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'Gerar tópico, roteiro e palavras-chave com IA' in source
    assert 'Gerar Thumbnail com IA' in source
    assert 'Gerar títulos e thumbnails com IA' not in source
    assert 'Gerar títulos e thumbnails para todos os canais' not in source
    assert 'SEM BLUEPRINT CONFIGURADO' in source
    assert 'Canais incluídos' not in source


def test_video_creation_has_exactly_four_primary_expanders_and_thumbnail_action():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'with st.expander("Configurações de vídeo", expanded=False):' in source
    assert 'with st.expander("Configurações de áudio", expanded=False):' in source
    assert 'with st.expander("Configurações de legendas", expanded=False):' in source
    assert 'with st.expander("Gerar Thumbnail com IA", expanded=False):' in source
    assert 'with st.expander("Advanced Script Settings", expanded=False):' not in source
    assert 'generate_thumbnail_variants_for_ui(' in source
    assert 'generated["title_candidates"] = existing_payload.get("title_candidates", [])' in source


def test_shorts_use_tiktok_channels_and_prompt_master():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'def render_tiktok_prompt_master_panel(' in source
    assert 'if channel_platform == "tiktok":' in source
    assert '"Criação de Shorts": lambda: render_new_video("Criação de Shorts", "new_shorts", channel_platform="tiktok", fixed_aspect_ratio="Portrait 9:16")' in source
    assert 'render_tiktok_prompt_master_panel(selected_one)' in source


def test_automation_card_matches_reference_layout_without_changing_control_keys():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    block = source.split('def _render_youtube_automation_channel_cards():', 1)[1].split('def render_automation():', 1)[0]
    assert 'header_cols = st.columns([0.58, 2.15, 1.4, 1.15, 1.15, 1.25, 0.82, 0.92], gap="small")' in block
    assert 'enabled = st.toggle("Automação ligada"' in block
    assert 'key=f"automation_on_{channel_id}"' in block
    assert 'key=f"automation_time_{channel_id}"' in block
    assert 'key=f"automation_save_{channel_id}"' in block
    assert 'control_cols = st.columns([1.8, 1.8, 1.35, 1.2], gap="small")' in block
    assert 'type="primary"' in block
    assert 'automation_format = st.selectbox' not in block
    assert 'st.markdown("**Formato**")' not in block


def test_general_mode_uses_all_registered_channels_without_partial_selector():
    source = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert 'selected = [str(channel["id"]) for channel in all_channels if channel.get("id")]' in source
    assert 'create_batch("general", selected, batch_topic, 1' in source
    assert 'channel_payloads' in source
