from pathlib import Path
import unittest

from hermes_ui.languages import LANGUAGE_CODES, UI_TRANSLATIONS


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


class ApiSettingsExpandersTests(unittest.TestCase):
    def test_api_settings_expandable_sections_are_closed_by_default(self):
        labels = [
            "Niche Finder — Kaggle",
            "Niche Finder — Apify",
            "Imagem e Video Montagem/MoviePy",
            "Imagem e Video IA",
            "Remotion",
            "Google Imagem API",
            "LLM — providers e modelos",
            "Voz, TTS e música — Azure Speech, restantes serviços e Suno",
            "Upload-Post",
            "Postiz",
        ]
        for label in labels:
            self.assertIn(f'st.expander("{label}", expanded=False)', MAIN_SOURCE)

    def test_voice_services_are_split_into_provider_cards(self):
        start = MAIN_SOURCE.index('with st.expander("Voz, TTS e música — Azure Speech, restantes serviços e Suno", expanded=False):')
        end = MAIN_SOURCE.index('with st.expander("Upload-Post", expanded=False):', start)
        voice_block = MAIN_SOURCE[start:end]
        for provider in ("Azure Speech", "ElevenLabs", "SiliconFlow", "MiniMax TTS", "Chatterbox", "Sonilo", "Suno — agente musical opcional"):
            self.assertIn(f'st.markdown("#### {provider}")', voice_block)
        self.assertNotIn('voice_test_cols', voice_block)
        for widget_key in (
            'api_test_voice_azure',
            'api_test_voice_elevenlabs',
            'api_test_voice_siliconflow',
            'api_test_voice_minimax',
            'api_test_voice_chatterbox',
            'api_test_voice_sonilo',
            'api_test_voice_suno',
        ):
            self.assertIn(f'widget_key="{widget_key}"', voice_block)

    def test_api_settings_form_and_saved_configuration_remain_present(self):
        self.assertIn('with st.form("settings_form"):', MAIN_SOURCE)
        self.assertIn('st.form_submit_button("Guardar configurações do Thunderbolt"', MAIN_SOURCE)

    def test_azure_speech_card_persists_values_before_diagnostic(self):
        self.assertIn('persist_callback: Any = None', MAIN_SOURCE)
        self.assertIn('if persist_callback is not None:', MAIN_SOURCE)
        self.assertIn('persist_callback()', MAIN_SOURCE)
        self.assertIn('def save_azure_speech() -> None:', MAIN_SOURCE)
        self.assertIn('"azure_speech_key": azure_speech_key.strip()', MAIN_SOURCE)
        self.assertIn('"azure_speech_region": azure_speech_region.strip()', MAIN_SOURCE)
        self.assertIn('key="save_azure_speech"', MAIN_SOURCE)
        self.assertIn('persist_callback=save_azure_speech', MAIN_SOURCE)

    def test_nvidia_nim_limit_card_is_inside_llm_expander_before_provider_cards(self):
        start = MAIN_SOURCE.index('def render_llm_provider_cards(')
        end = MAIN_SOURCE.index('def _media_card_config_status(', start)
        llm_block = MAIN_SOURCE[start:end]
        self.assertIn('with st.expander("LLM — providers e modelos", expanded=False):', llm_block)
        limit_position = llm_block.index('st.markdown("### Limite LLM NVIDIA NIM")')
        first_provider_position = llm_block.index('for index in range(len(cards)):')
        self.assertLess(limit_position, first_provider_position)
        settings_start = MAIN_SOURCE.index('def render_settings():')
        settings_block = MAIN_SOURCE[settings_start:]
        self.assertNotIn('st.markdown("### Limite LLM NVIDIA NIM")', settings_block)

    def test_llm_and_media_sections_are_in_main_list_after_apify(self):
        llm_position = MAIN_SOURCE.index('render_llm_provider_cards(settings, embedded=True)')
        apify_position = MAIN_SOURCE.index('with st.expander("Niche Finder — Apify", expanded=False)')
        settings_position = MAIN_SOURCE.index('def render_settings():')
        material_position = MAIN_SOURCE.index('render_material_source_api_keys(settings, embedded=True)', settings_position)
        media_position = MAIN_SOURCE.index('render_media_provider_cards(settings, embedded=True)', settings_position)
        self.assertLess(apify_position, llm_position)
        self.assertLess(llm_position, material_position)
        self.assertLess(material_position, media_position)
        self.assertIn('with st.expander("Imagem e Video Montagem/MoviePy", expanded=False)', MAIN_SOURCE)
        self.assertIn('with st.expander("Imagem e Video IA", expanded=False)', MAIN_SOURCE)
        remotion_position = MAIN_SOURCE.index('with st.expander("Remotion", expanded=False)', settings_position)
        google_images_position = MAIN_SOURCE.index('with st.expander("Google Imagem API", expanded=False)', settings_position)
        voice_position = MAIN_SOURCE.index('with st.expander("Voz, TTS e música — Azure Speech, restantes serviços e Suno", expanded=False)', settings_position)
        self.assertLess(media_position, remotion_position)
        self.assertLess(remotion_position, google_images_position)
        self.assertLess(google_images_position, voice_position)
        self.assertIn('Integração do Remotion como provedor de vídeo será implementada na Etapa 2.', MAIN_SOURCE)
        self.assertIn('Integração da API do Google Custom Search (Google Images) será implementada na Etapa 2.', MAIN_SOURCE)
        self.assertNotIn('Nano Banana — geração de thumbnails', MAIN_SOURCE)
        self.assertNotIn('Niche Finder — execução remota no Kaggle', MAIN_SOURCE)
        self.assertNotIn('Niche Finder — execução através da Apify', MAIN_SOURCE)

    def test_media_cards_keep_rendering_constraints_out_of_provider_forms(self):
        media_renderer = MAIN_SOURCE[MAIN_SOURCE.index('def _render_media_provider_card('):MAIN_SOURCE.index('def render_media_provider_cards(')]
        self.assertNotIn('Aspect Ratio', media_renderer)
        self.assertNotIn('Image Size', media_renderer)
        self.assertNotIn('aspect_ratio', media_renderer)
        self.assertNotIn('image_size', media_renderer)

    def test_media_pool_order_has_no_redundant_top_selectors(self):
        media_page = MAIN_SOURCE[MAIN_SOURCE.index('def render_media_provider_cards('):MAIN_SOURCE.index('def render_settings(')]
        for label in (
            'Provider principal de imagem',
            'Provider principal de vídeo',
            'Usar pool de vídeo externo',
            'Salvar selecção dos pools',
        ):
            self.assertNotIn(label, media_page)
        media_renderer = MAIN_SOURCE[MAIN_SOURCE.index('def _render_media_provider_card('):MAIN_SOURCE.index('def render_media_provider_cards(')]
        self.assertIn('"Prioridade"', media_renderer)

    def test_llm_card_uses_priority_instead_of_primary_checkbox(self):
        llm_renderer = MAIN_SOURCE[MAIN_SOURCE.index('def _render_llm_card('):MAIN_SOURCE.index('def render_llm_provider_cards(')]
        self.assertIn('st.number_input(', llm_renderer)
        self.assertIn('"Prioridade"', llm_renderer)
        self.assertNotIn('LLM principal', llm_renderer)
        self.assertNotIn('primary_llm', llm_renderer)
        self.assertNotIn('llm_card_{card_id}_primary', llm_renderer)

    def test_telegram_llm_card_disables_and_explains_priority(self):
        llm_renderer = MAIN_SOURCE[MAIN_SOURCE.index('def _render_llm_card('):MAIN_SOURCE.index('def render_llm_provider_cards(')]
        self.assertIn('disabled=bool(telegram_llm)', llm_renderer)
        self.assertIn('Exclusivo para Notificações de Telegram — prioridade ignorada no pool LLM.', llm_renderer)
        routing_source = (ROOT / 'hermes_ui' / 'provider_routing.py').read_text(encoding='utf-8')
        self.assertIn('not bool(card.get("telegram_llm", False))', routing_source)

    def test_llm_card_matches_reference_layout_structure(self):
        self.assertIn('endpoint_col, action_col = st.columns([1.65, 1.05])', MAIN_SOURCE)
        self.assertIn('action_buttons = st.columns(2)', MAIN_SOURCE)
        self.assertIn('status_cols = st.columns(3)', MAIN_SOURCE)
        self.assertIn('save_clicked = st.form_submit_button("Salvar", type="primary", width="stretch", key=f"llm_card_{card_id}_save")', MAIN_SOURCE)

    def test_api_keys_use_direct_tabs_and_material_sources_are_inside_api_keys(self):
        tabs_position = MAIN_SOURCE.index('api_keys_tab, upload_api_keys_tab, subtitles_tab, ffmpeg_tab, ai_influencers_tab, test_upload_videos_tab, voice_test_tab = render_localized_tabs(["API Keys", "API Keys Upload", "Legendas", "FFmpeg", "AI Influencers", "Test Upload Videos", "Teste de Voz"])')
        api_position = MAIN_SOURCE.index('    with api_keys_tab:', tabs_position)
        api_block = MAIN_SOURCE[api_position:MAIN_SOURCE.index('    with upload_api_keys_tab:', api_position)]
        material_position = api_block.index('render_material_source_api_keys(settings, embedded=True)')
        media_position = api_block.index('render_media_provider_cards(settings, embedded=True)')
        self.assertLess(material_position, media_position)
        self.assertIn('with st.expander("Imagem e Video Montagem/MoviePy", expanded=False):', MAIN_SOURCE)
        self.assertIn('with st.expander("Imagem e Video IA", expanded=False):', MAIN_SOURCE)
        self.assertIn('with st.container(border=True):', api_block)
        self.assertIn('with st.form("settings_form"):', api_block)
        self.assertNotIn('with material_sources_tab:', MAIN_SOURCE)

    def test_material_sources_use_individual_cards_and_add_provider_button(self):
        self.assertIn('def _render_material_source_card(', MAIN_SOURCE)
        self.assertIn('with st.container(border=True):', MAIN_SOURCE[MAIN_SOURCE.index('def _render_material_source_card('):])
        self.assertIn('Configurar Nova Fonte de Materiais', MAIN_SOURCE)
        self.assertIn('key="add_material_source_card"', MAIN_SOURCE)
        self.assertIn('MATERIAL_CARDS_KEY = "material_source_cards"', (ROOT / "hermes_ui" / "material_sources.py").read_text(encoding="utf-8"))

    def test_material_sources_expander_is_safe_inside_api_keys_form(self):
        material_renderer = MAIN_SOURCE[MAIN_SOURCE.index('def _render_material_source_card('):MAIN_SOURCE.index('def _api_status_badge(')]
        self.assertIn('embedded: bool = False', material_renderer)
        self.assertIn('card_form = nullcontext() if embedded else st.form(', material_renderer)
        self.assertIn('render_material_source_api_keys(settings, embedded=True)', MAIN_SOURCE)
        self.assertIn('st.form_submit_button("Configurar Nova Fonte de Materiais"', material_renderer)
        self.assertIn('if embedded else st.button', material_renderer)

    def test_streamlit_port_is_not_rendered_and_video_engine_path_is_read_only(self):
        self.assertNotIn('st.number_input("Porta Streamlit"', MAIN_SOURCE)
        self.assertNotIn('st.text_input("Pasta do motor de vídeo"', MAIN_SOURCE)
        self.assertIn('moneyprinter_path = str(settings.get("moneyprinter_path") or "").strip()', MAIN_SOURCE)
        self.assertIn('st.caption(f"Pasta do motor de vídeo:', MAIN_SOURCE)

    def test_llm_api_key_success_message_is_short_and_model_count_is_not_shown(self):
        self.assertIn('st.success("Último teste: API Key OK")', MAIN_SOURCE)
        self.assertNotIn('API OK — {_safe_url(base_url)} respondeu com {len(models)} modelo(s).', MAIN_SOURCE)

    def test_every_non_llm_api_key_expander_has_a_diagnostic_control(self):
        expected_controls = (
            'widget_key="api_test_kaggle"',
            'widget_key="api_test_apify"',
            'def render_media_provider_cards(',
            'test_media_provider_card(edited)',
            'widget_key="api_test_voice_azure"',
            'widget_key="api_test_voice_siliconflow"',
            'widget_key="api_test_voice_minimax"',
            'widget_key="api_test_voice_elevenlabs"',
            'widget_key="api_test_voice_chatterbox"',
            'widget_key="api_test_voice_sonilo"',
            'widget_key="api_test_voice_suno"',
            'def render_tiktok_api_cards(',
            'test_tiktok_credentials(edited["client_id"], edited["client_secret"]',
        )
        for control in expected_controls:
            self.assertIn(control, MAIN_SOURCE)
        self.assertIn('if st.form_submit_button("Testar chamada API"', MAIN_SOURCE)
        self.assertIn('st.form_submit_button("Testar Chamada API"', MAIN_SOURCE)
        self.assertIn('test_media_provider_card(edited)', MAIN_SOURCE)
        self.assertIn('settings["api_test_results"] = stored', MAIN_SOURCE)
        self.assertNotIn('widget_key="api_test_llm"', MAIN_SOURCE)

    def test_material_remote_cards_have_diagnostic_controls_but_local_source_does_not_fake_one(self):
        self.assertIn('test_material_source_credentials(provider, api_key)', MAIN_SOURCE)
        self.assertIn('f"material:{card_id}"', MAIN_SOURCE)
        self.assertIn('if not is_local:', MAIN_SOURCE)

    def test_new_api_tab_titles_have_all_language_translations(self):
        for language in LANGUAGE_CODES:
            self.assertIn("API Keys", UI_TRANSLATIONS[language])
            self.assertIn("Contas Google", UI_TRANSLATIONS[language])
            self.assertIn("Fontes de Materiais", UI_TRANSLATIONS[language])
            self.assertIn("Teste de Voz", UI_TRANSLATIONS[language])

    def test_material_card_labels_have_all_language_translations(self):
        labels = (
            "Configurar Nova Fonte de Materiais",
            "Provedor de materiais",
            "Fonte activa",
            "Usar esta fonte na pipeline",
            "Esta fonte não usa API key.",
        )
        for language in LANGUAGE_CODES:
            for label in labels:
                self.assertIn(label, UI_TRANSLATIONS[language])

    def test_new_api_expander_titles_have_all_language_translations(self):
        for language in LANGUAGE_CODES:
            self.assertIn("Niche Finder — Kaggle", UI_TRANSLATIONS[language])
            self.assertIn("Niche Finder — Apify", UI_TRANSLATIONS[language])
            self.assertIn("Imagem e Video IA", UI_TRANSLATIONS[language])
            self.assertIn("Imagem e Video Montagem/MoviePy", UI_TRANSLATIONS[language])

    def test_api_test_feedback_has_all_language_translations(self):
        labels = (
            "Testar chamada API",
            "A testar chamada API…",
            "Último teste: API Key OK",
            "Último teste: falta configuração",
            "Último teste: requer autorização ou endpoint seguro",
            "Último teste: chamada falhou",
            "Testar credenciais TTS e música",
        )
        for language in LANGUAGE_CODES:
            for label in labels:
                self.assertIn(label, UI_TRANSLATIONS[language])


if __name__ == "__main__":
    unittest.main()
