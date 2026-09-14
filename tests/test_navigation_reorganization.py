from pathlib import Path
import unittest

from hermes_ui.languages import ui_text


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
LANGUAGES_SOURCE = (ROOT / "hermes_ui" / "languages.py").read_text(encoding="utf-8")


class NavigationReorganizationTests(unittest.TestCase):
    def test_top_level_order_matches_requested_structure(self):
        expected_order = [
            '"Início"',
            '"Automação"',
            '"Niche Finder"',
            '"Canais/Perfis (Vídeos)"',
            '"Pipeline Vídeos"',
            '"Pipeline Música"',
            '"AI Influencers"',
            '"Edição"',
            '"Growth"',
            '"Documentação"',
            '"Configurações"',
        ]
        top_block = MAIN_SOURCE.split("    top_pages = [", 1)[1].split("    ]", 1)[0]
        positions = [top_block.index(item) for item in expected_order]
        self.assertEqual(positions, sorted(positions))

    def test_navigation_icons_are_valid_and_settings_remains_visible(self):
        self.assertNotIn(":material/facebook:", MAIN_SOURCE)
        self.assertIn('(\"Facebook Pages\", \":material/public:\", \"Facebook Pages\")', MAIN_SOURCE)
        self.assertIn('("Configurações", ":material/settings:", "Configurações")', MAIN_SOURCE)
        self.assertIn('"Música": "Pipeline Música"', MAIN_SOURCE)

    def test_navigation_widget_keys_are_scoped_by_group(self):
        self.assertIn('key=f"nav_{scope}_{target}"', MAIN_SOURCE)
        self.assertIn('render_nav_button(child_target, child_icon, child_label, target)', MAIN_SOURCE)
        self.assertNotIn('key=f"nav_{target}"', MAIN_SOURCE)

    def test_tiktok_navigation_uses_channels_page_only(self):
        channel_block = MAIN_SOURCE.split("    channel_profile_items = [", 1)[1].split("    blueprint_items = [", 1)[0]
        self.assertIn('("Canais Tiktok",', channel_block)
        self.assertNotIn('("Contas TikTok",', channel_block)
        self.assertIn('"Canais Tiktok": "/canais-perfis-videos/canais-tiktok"', MAIN_SOURCE)
        self.assertNotIn('"Contas TikTok": "/canais-perfis-videos/contas-tiktok"', MAIN_SOURCE)
        self.assertIn('"Canais Tiktok": render_tiktok_channels', MAIN_SOURCE)
        self.assertNotIn('"Contas TikTok": render_tiktok_accounts', MAIN_SOURCE)

    def test_niche_finder_tutorials_are_documentation_only(self):
        niche_block = MAIN_SOURCE.split("    niche_finder_items = [", 1)[1].split("    ]", 1)[0]
        documentation_block = MAIN_SOURCE.split("    documentation_items = [", 1)[1].split("    ]", 1)[0]
        for label in ("Tutorial Kaggle", "Tutorial Apify"):
            self.assertNotIn(f'("{label}"', niche_block)
            self.assertIn(f'("{label}"', documentation_block)

    def test_requested_groups_and_children_are_present(self):
        required = (
            "Canais/Perfis (Vídeos)", "Canais YouTube", "Canais Tiktok", "Blueprints Youtube", "Thumbnail Blueprints", "Brandings Youtube", "Prompt Masters", "Facebook Pages",
            "Pipeline Vídeos", "Criação de Vídeos", "Backlog Vídeos", "Roteiros", "Thumbnails", "Upload",
            "AI Influencers", "Personagens", "Geração de Conteúdo IA", "UGC Products", "Contas Instagram",
            "Pipeline Música", "Criação de Músicas", "Upload Música",
            "Growth", "Analista Growth Youtube", "Analista Growth Tiktok", "Analista Growth Instagram", "Analista Facebook Pages", "Analista Bilibili",
            "Documentação", "Tutorial Meta", "Tutorial Supabase", "Tutorial Kaggle", "Tutorial Apify",
        )
        for label in required:
            self.assertIn(f'"{label}"', MAIN_SOURCE)

    def test_channel_profile_children_match_requested_order(self):
        channel_block = MAIN_SOURCE.split("    channel_profile_items = [", 1)[1].split("    ]", 1)[0]
        expected_children = [
            '("Canais YouTube",',
            '("Canais Tiktok",',
            '("Contas Instagram",',
            '("Facebook Pages",',
            '("Blueprints Youtube",',
            '("Thumbnail Blueprints",',
            '("Brandings Youtube",',
            '("Prompt Masters",',
        ]
        positions = [channel_block.index(item) for item in expected_children]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('"Thumbnail Blueprints": "/canais-perfis-videos/thumbnail-blueprints"', MAIN_SOURCE)
        self.assertIn('"Brandings Youtube": "/canais-perfis-videos/brandings-youtube"', MAIN_SOURCE)
        self.assertIn('"Thumbnail Blueprints": render_thumbnail_blueprints', MAIN_SOURCE)
        self.assertIn('"Brandings Youtube": render_youtube_brandings', MAIN_SOURCE)
        self.assertIn('def render_thumbnail_blueprints():', MAIN_SOURCE)

    def test_requested_empty_automation_pages_are_present(self):
        automation_block = MAIN_SOURCE.split("    automation_items = [", 1)[1].split("    ]", 1)[0]
        labels = ("Automação Facebook", "Automação Musicas", "Automação UGC", "Automação Influencer Content", "Automação Bilibili")
        for label in labels:
            self.assertIn(f'("{label}",', automation_block)
            expected_renderer = 'render_facebook_automation' if label == "Automação Facebook" else 'lambda: None'
            self.assertIn(f'"{label}": {expected_renderer}', MAIN_SOURCE)

    def test_instagram_and_facebook_pages_are_video_profile_children(self):
        channel_block = MAIN_SOURCE.split("    channel_profile_items = [", 1)[1].split("    ]", 1)[0]
        self.assertLess(channel_block.index('("Contas Instagram",'), channel_block.index('("Facebook Pages",'))
        self.assertIn('"Contas Instagram": "/canais-perfis-videos/contas-instagram"', MAIN_SOURCE)
        self.assertIn('"Facebook Pages": render_facebook_pages', MAIN_SOURCE)

    def test_video_backlog_is_not_nested_inside_video_creation(self):
        self.assertIn('tab_labels = ["Criar vídeo"] + (["Gerar de Rascunho"] if page_title == "Criação de Vídeos" else [])', MAIN_SOURCE)
        self.assertIn('draft_tab = tabs[1] if len(tabs) > 1 else None', MAIN_SOURCE)
        self.assertNotIn("with videos_tab:", MAIN_SOURCE)
        self.assertIn('"Backlog Vídeos": render_videos', MAIN_SOURCE)

    def test_thumbnails_is_immediately_before_upload(self):
        pipeline_block = MAIN_SOURCE.split("    pipeline_video_items = [", 1)[1].split("    ]", 1)[0]
        self.assertLess(pipeline_block.index('("Thumbnails"'), pipeline_block.index('("Upload"'))
        self.assertIn('"Thumbnails": render_thumbnails', MAIN_SOURCE)

    def test_batch_success_message_points_to_video_backlog(self):
        self.assertIn("Abra {ui_text('Backlog Vídeos', current_ui_language())} para acompanhar.", MAIN_SOURCE)
        self.assertNotIn("Abra a subaba Vídeos para acompanhar.", MAIN_SOURCE)

    def test_settings_order_keeps_notifications_before_api(self):
        settings_block = MAIN_SOURCE.split("    settings_items = [", 1)[1].split("    ]", 1)[0]
        self.assertLess(settings_block.index('"Notificações"'), settings_block.index('"Configuração API"'))

    def test_google_accounts_are_moved_to_api_settings_subtab(self):
        settings_block = MAIN_SOURCE.split("    settings_items = [", 1)[1].split("    ]", 1)[0]
        self.assertNotIn('("Contas Google",', settings_block)
        self.assertIn('api_keys_tab, upload_api_keys_tab, subtitles_tab, ai_influencers_tab, voice_test_tab = render_localized_tabs(["API Keys", "API Keys Upload", "Legendas", "AI Influencers", "Teste de Voz"])', MAIN_SOURCE)
        self.assertIn('with st.expander("API Instagram", expanded=False):', MAIN_SOURCE)
        self.assertIn('with st.expander("API Facebook Pages", expanded=False):', MAIN_SOURCE)
        self.assertIn('"Contas Google": "Configuração API"', MAIN_SOURCE)

    def test_channels_are_always_rendered_in_the_list_view(self):
        self.assertNotIn('st.radio("Apresentação dos canais", ["Lista", "Kanban"]', MAIN_SOURCE)
        self.assertNotIn('key="youtube_channels_view_mode"', MAIN_SOURCE)
        self.assertNotIn('render_registered_channels_kanban(channels)', MAIN_SOURCE)
        self.assertIn('for channel in channels:', MAIN_SOURCE)
        self.assertNotIn('channel_videos_view_', MAIN_SOURCE)

    def test_list_cards_keep_the_shared_outline_style(self):
        self.assertIn('.content-card { border:1px solid color-mix(in srgb, currentColor 18%, transparent);', MAIN_SOURCE)
        self.assertIn('with st.container(border=True):', MAIN_SOURCE)
        self.assertIn('st.columns(4, gap="small")', MAIN_SOURCE)

    def test_list_mode_keeps_registered_channel_cards_and_video_details(self):
        list_branch = MAIN_SOURCE.split('    for channel in channels:', 1)[1]
        self.assertIn('with st.container(border=True):', list_branch)
        self.assertIn('render_channel_videos(channel)', list_branch)
        self.assertIn('render_channel_video_editor(video, channel_id)', MAIN_SOURCE)

    def test_channel_default_labels_have_translations_for_all_languages(self):
        languages = ("pt", "en", "zh", "de", "vi", "tr", "ru", "es", "id", "it")
        labels = ("Idioma", "Blueprint Padrão", "Nicho", "Narrador/Voz Padrão", "YouTube", "Inscritos", "Vídeos", "Activo", "Inactivo")
        for language in languages:
            for label in labels:
                self.assertTrue(ui_text(label, language).strip(), f"empty translation for {label} in {language}")

    def test_navigation_labels_have_translations_for_all_languages(self):
        languages = ("pt", "en", "zh", "de", "vi", "tr", "ru", "es", "id", "it")
        labels = (
            "Pipeline Vídeos", "Canais/Perfis (Vídeos)", "Canais YouTube",
            "Facebook Pages", "Prompt Masters", "Backlog Vídeos", "Música", "Upload Música",
            "Geração de Conteúdo IA", "Motion Control", "UGC Products", "Growth",
            "Analista Growth Youtube", "Analista Growth Tiktok", "Analista Growth Instagram", "Analista Facebook Pages", "Analista Bilibili",
            "Documentação", "Tutorial Kaggle", "Tutorial Apify", "Pipeline Música", "Thumbnails", "módulos disponíveis",
        )
        navigation_source = LANGUAGES_SOURCE.split("UI_NAV_TRANSLATIONS", 1)[1]
        for language in languages:
            language_block = navigation_source.split(f'    "{language}": {{', 1)[1].split("    },", 1)[0]
            for label in labels:
                self.assertIn(f'"{label}"', language_block, f"missing {label} source key for {language}")
                self.assertTrue(ui_text(label, language).strip(), f"empty translation for {label} in {language}")


if __name__ == "__main__":
    unittest.main()


def test_confirmed_video_profiles_children_are_ordered_and_base_files_is_removed():
    channel_block = MAIN_SOURCE.split("    channel_profile_items = [", 1)[1].split("    ]", 1)[0]
    expected_children = [
        '("Canais YouTube",',
        '("Canais Tiktok",',
        '("Contas Instagram",',
        '("Facebook Pages",',
        '("Blueprints Youtube",',
        '("Thumbnail Blueprints",',
        '("Brandings Youtube",',
        '("Prompt Masters",',
    ]
    positions = [channel_block.index(item) for item in expected_children]
    assert positions == sorted(positions)
    assert 'base_files_items = [' not in MAIN_SOURCE
    assert '("Arquivos Base", ":material/folder:", "Arquivos Base")' not in MAIN_SOURCE
    assert '"Arquivos Base": base_files_items' not in MAIN_SOURCE
    top_block = MAIN_SOURCE.split("    top_pages = [", 1)[1].split("    ]", 1)[0]
    assert '"Canais/Perfis (Vídeos)"' in top_block
    assert '"Arquivos Base"' not in top_block
