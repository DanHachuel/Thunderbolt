from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_stage2_sources_are_marked_unavailable():
    assert 'UNAVAILABLE_VIDEO_SOURCES = {"google_images", "remotion", "music_clips"}' in MAIN_SOURCE
    assert 'style in UNAVAILABLE_VIDEO_SOURCES' in MAIN_SOURCE
    assert 'Esta fonte será implementada na Etapa 2. Nenhuma tarefa será criada.' in MAIN_SOURCE


def test_stage2_placeholder_form_is_disabled_and_stops_before_generation():
    start = MAIN_SOURCE.index('if style in UNAVAILABLE_VIDEO_SOURCES:', MAIN_SOURCE.index('wide_style_label ='))
    end = MAIN_SOURCE.index('material_source =', start)
    block = MAIN_SOURCE[start:end]
    assert 'st.form_submit_button("Criar tarefas", type="primary", disabled=True)' in block
    assert 'st.stop()' in block
    assert MAIN_SOURCE.index('wide_style_label =') < start < MAIN_SOURCE.index('material_source =', start)


def test_placeholder_path_does_not_write_or_call_workers_before_stop():
    start = MAIN_SOURCE.index('if style in UNAVAILABLE_VIDEO_SOURCES:', MAIN_SOURCE.index('wide_style_label ='))
    end = MAIN_SOURCE.index('material_source =', start)
    block = MAIN_SOURCE[start:end]
    assert "write_json(" not in block
    assert "create_task(" not in block
    assert "create_batch(" not in block
    assert "run_worker(" not in block


def test_api_placeholders_have_no_settings_inputs_or_validation():
    start = MAIN_SOURCE.index('with st.expander("Remotion", expanded=False)')
    end = MAIN_SOURCE.index('with st.expander("Voz, TTS e música — Azure Speech, restantes serviços e Suno", expanded=False)', start)
    block = MAIN_SOURCE[start:end]
    assert 'st.caption("Integração do Remotion como provedor de vídeo será implementada na Etapa 2.")' in block
    assert 'st.caption("Integração da API do Google Custom Search (Google Images) será implementada na Etapa 2.")' in block
    assert 'st.info(' in block
    assert 'st.text_input(' not in block
    assert 'st.button(' not in block
    assert 'write_json(' not in block
    assert 'settings[' not in block


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
