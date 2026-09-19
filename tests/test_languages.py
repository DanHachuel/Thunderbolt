from pathlib import Path

from hermes_ui.languages import FLAG_DATA_URIS_BY_ISO, LANGUAGE_CATALOG, LANGUAGE_CODES, LANGUAGE_FLAG_DATA_URIS, LANGUAGE_FLAG_SVGS, TAB_TRANSLATIONS, _TAB_LABELS, language_code, language_label, replace_flag_emojis, translate_ui_content, ui_language_menu_label, ui_text, video_language_label
from integrations.moneyprinter_config import build_moneyprinter_config


ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
STORAGE_SOURCE = (ROOT / "hermes_ui" / "storage.py").read_text(encoding="utf-8")


def test_moneyprinter_language_catalog_has_requested_codes_and_flags():
    assert LANGUAGE_CODES == ("en", "zh", "de", "vi", "tr", "pt", "ru", "es", "id", "it", "pl", "ga", "ar", "he")
    assert [item["flag"] for item in LANGUAGE_CATALOG] == ["🇺🇸", "🇨🇳", "🇩🇪", "🇻🇳", "🇹🇷", "🇧🇷", "🇷🇺", "🇪🇸", "🇮🇩", "🇮🇹", "🇵🇱", "🇮🇪", "🇸🇦", "🇮🇱"]
    assert language_label("en") == "Inglês (en) 🇺🇸"
    assert language_label("zh") == "Chinês Simplificado (zh) 🇨🇳"
    assert ui_language_menu_label("ru") == "Russian"
    assert set(LANGUAGE_FLAG_DATA_URIS) == set(LANGUAGE_CODES)
    assert all(uri.startswith("data:image/svg+xml;base64,") for uri in LANGUAGE_FLAG_DATA_URIS.values())


def test_flag_emojis_use_local_svg_assets_and_preserve_unknown_pairs():
    converted = replace_flag_emojis("Origem 🇧🇷 e destino 🇩🇪.")

    assert 'class="tb-flag-icon"' in converted
    assert 'alt="BR"' in converted
    assert 'alt="DE"' in converted
    assert converted.count("data:image/svg+xml;base64,") == 2
    assert replace_flag_emojis("Código desconhecido 🇽🇽") == "Código desconhecido 🇽🇽"
    assert replace_flag_emojis(123) == 123
    assert set(FLAG_DATA_URIS_BY_ISO) == {"US", "CN", "DE", "VN", "TR", "BR", "RU", "ES", "ID", "IT", "PL", "IE", "SA", "IL"}


def test_language_normalization_preserves_legacy_values():
    assert language_code("36 – Português (Brasil)") == "pt"
    assert language_code("01 – Inglês") == "en"
    assert language_code("42 – Vietnamita") == "vi"
    assert language_code("44 – Indonésio") == "id"
    assert video_language_label("music").startswith("🎵")
    assert "🇷🇺" in video_language_label("ru")


def test_ui_translation_and_header_picker_are_present():
    assert ui_text("Configurações", "es") == "Configuración"
    assert ui_text("Pipeline", "zh") == "视频流程"
    assert ui_text("Canais", "ru") == "Каналы"
    assert ui_text("Niche", "it") == "Nicchia"
    assert "def render_ui_language_picker(language: str)" in MAIN_SOURCE
    assert '"Language"' in MAIN_SOURCE
    assert "top_language_code_selector" in MAIN_SOURCE
    assert "format_func=ui_language_menu_label" in MAIN_SOURCE
    assert "label_visibility=\"visible\"" in MAIN_SOURCE
    assert "LANGUAGE_FLAG_DATA_URIS" in MAIN_SOURCE
    assert "_FLAG_RENDER_BOOTSTRAP" in MAIN_SOURCE
    assert "tb-flag-icon" in MAIN_SOURCE
    assert 'aria-label="Language"' in MAIN_SOURCE
    assert "st.popover" not in MAIN_SOURCE
    assert "stAppDeployButton" not in MAIN_SOURCE
    assert "stMainMenu" not in MAIN_SOURCE
    assert "save_ui_language(selected)" in MAIN_SOURCE
    assert "Interface local para operação e automação de conteúdo faceless" in MAIN_SOURCE
    assert "ui_text(\"Filas locais e dependências da cascata\", ui_language)" in MAIN_SOURCE
    assert '"ui_language": "pt"' in STORAGE_SOURCE


def test_internal_content_labels_translate_in_all_supported_languages():
    examples = {
        "en": {"Título": "Title", "Video Settings": "Video Settings", "Gerar com IA a partir do Blueprint": "Generate with AI from Blueprint"},
        "zh": {"Título": "标题", "Descrição": "描述", "Upload": "上传"},
        "de": {"Título": "Titel", "Canais": "Kanäle", "Guardar": "Speichern"},
        "vi": {"Título": "Tiêu đề", "Upload": "Tải lên", "Pesquisar": "Tìm kiếm"},
        "tr": {"Título": "Başlık", "Canais": "Kanallar", "Apagar": "Sil"},
        "ru": {"Título": "Заголовок", "Descrição": "Описание", "Cancelar": "Отмена"},
        "es": {"Título": "Título", "Canais": "Canales", "Pesquisar": "Buscar"},
        "id": {"Título": "Judul", "Descrição": "Deskripsi", "Guardar": "Simpan"},
        "it": {"Título": "Titolo", "Canais": "Canali", "Apagar": "Elimina"},
    }
    for code, expected in examples.items():
        for source, translated in expected.items():
            assert translate_ui_content(source, code) == translated
    assert translate_ui_content("private", "en") == "private"
    assert translate_ui_content("full_ia", "de") == "full_ia"
    assert "API Configuration" in translate_ui_content("Configure em Configuração API", "en")
    assert "Google account" in translate_ui_content("Conta Google para Upload directo", "en")


def test_page_content_translation_covers_all_supported_languages():
    page_examples = {
        "en": {
            "Operações notificadas": "Notified operations",
            "Filtrar palavras-chave nos clusters": "Filter keywords in clusters",
            "Metadados para a versão limpa": "Metadata for the cleaned version",
        },
        "zh": {
            "Operações notificadas": "已通知的操作",
            "Plataformas Upload-Post": "Upload-Post 平台",
            "Histórico de notificações": "通知历史",
        },
        "de": {
            "Operações notificadas": "Benachrichtigte Vorgänge",
            "Processar em segundo plano": "Im Hintergrund verarbeiten",
            "Resultado": "Ergebnis",
        },
        "vi": {
            "Operações notificadas": "Hoạt động được thông báo",
            "Metadados para a versão limpa": "Siêu dữ liệu cho phiên bản đã làm sạch",
            "Descarregar legendas": "Tải phụ đề",
        },
        "tr": {
            "Operações notificadas": "Bildirim gönderilen işlemler",
            "Processar em segundo plano": "Arka planda işle",
            "Resultado": "Sonuç",
        },
        "pt": {
            "Operações notificadas": "Operações notificadas",
            "Processar em segundo plano": "Processar em segundo plano",
            "Metadados para a versão limpa": "Metadados para a versão limpa",
        },
        "ru": {
            "Operações notificadas": "Операции с уведомлениями",
            "Histórico de notificações": "История уведомлений",
            "Descarregar legendas": "Скачать субтитры",
        },
        "es": {
            "Operações notificadas": "Operaciones notificadas",
            "Processar em segundo plano": "Procesar en segundo plano",
            "Resultado": "Resultado",
        },
        "id": {
            "Operações notificadas": "Operasi yang diberi notifikasi",
            "Histórico de notificações": "Riwayat notifikasi",
            "Descarregar legendas": "Unduh subtitle",
        },
        "it": {
            "Operações notificadas": "Operazioni notificate",
            "Processar em segundo plano": "Elabora in background",
            "Resultado": "Risultato",
        },
    }
    for code, examples in page_examples.items():
        for source, expected in examples.items():
            assert translate_ui_content(source, code) == expected


def test_global_content_translation_hook_is_installed_before_page_renderers():
    assert "install_streamlit_content_translation()" in MAIN_SOURCE
    assert "_CONTENT_TRANSLATED_STREAMLIT_METHODS" in MAIN_SOURCE
    assert "_OPTION_TRANSLATED_STREAMLIT_METHODS" in MAIN_SOURCE
    assert "translate_ui_content" in MAIN_SOURCE or "ui_text" in MAIN_SOURCE


def test_moneyprinter_config_persists_ui_and_video_language_codes():
    payload = build_moneyprinter_config({"ui_language": "de", "video_language": "it"})
    assert payload["ui"]["language"] == "de"
    assert payload["ui"]["video_language"] == "it"


def test_video_selector_uses_flag_formatter_and_canonical_codes():
    assert "VIDEO_LANGUAGE_SELECTION_OPTIONS" in MAIN_SOURCE
    assert "format_func=video_language_label" in MAIN_SOURCE
    assert '"video_language": "pt"' in STORAGE_SOURCE


def test_all_language_labels_use_name_then_code_then_flag():
    for item in LANGUAGE_CATALOG:
        assert language_label(item["code"]) == f'{item["name"]} ({item["code"]}) {item["flag"]}'


def test_all_supported_ui_languages_cover_dashboard_and_sidebar_keys():
    from hermes_ui.languages import UI_TRANSLATIONS, _CORE_UI_TEXT_KEYS

    for code in LANGUAGE_CODES:
        assert set(_CORE_UI_TEXT_KEYS).issubset(UI_TRANSLATIONS[code])


def test_brazil_flag_svg_uses_official_color_order():
    brazil = LANGUAGE_FLAG_SVGS["pt"]
    assert '<rect width="30" height="20" fill="#009c3b"/>' in brazil
    assert '<path fill="#ffdf00"' in brazil
    assert '<circle cx="15" cy="10" r="4.2" fill="#002776"/>' in brazil
    assert '<rect width="30" height="20" fill="#ffdf00"/>' not in brazil


def test_all_tab_and_subtab_labels_are_translated_for_every_supported_language():
    assert len(_TAB_LABELS) == 32
    assert "render_localized_tabs" in MAIN_SOURCE
    for code in LANGUAGE_CODES:
        assert set(_TAB_LABELS).issubset(TAB_TRANSLATIONS[code])
    assert ui_text("Pesquisa pública", "en") == "Public search"
    assert ui_text("Cadastro manual", "zh") == "手动注册"
    assert ui_text("Importar do YouTube", "de") == "Von YouTube importieren"
    assert ui_text("Teste de Voz", "es") == "Prueba de voces"
    assert ui_text("Serviços e modelos", "it") == "Servizi e modelli"
