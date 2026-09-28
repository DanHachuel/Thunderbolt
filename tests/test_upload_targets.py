from pathlib import Path


SOURCE = Path(__file__).parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")


def test_upload_destinations_render_a_target_selector_for_each_platform():
    assert 'st.markdown("**Onde enviar**")' in SOURCE
    assert 'render_upload_destination_target(target_destination, channels, settings)' in SOURCE
    assert 'key=f"upload_target_{destination_key}"' in SOURCE


def test_youtube_upload_keeps_channel_optional_until_the_upload_action():
    assert 'selected_youtube_channel = upload_targets.get("YouTube")' in SOURCE
    assert 'channel = selected_youtube_channel or channel_map.get' in SOURCE
    assert 'disabled=not selected_youtube_channel' not in SOURCE
    assert 'Nenhum canal YouTube disponível; o destino permanece vazio' in SOURCE


def test_future_platform_target_lists_are_reserved_in_settings():
    assert '"TikTok": "tiktok_accounts"' in SOURCE
    assert 'settings.get("tiktok_profiles", [])' in SOURCE
    assert '"Instagram": "instagram_profiles"' in SOURCE
    assert '"Facebook Pages": "facebook_pages"' in SOURCE
    assert 'st.selectbox(select_label, [""], format_func=lambda _value: empty_label' in SOURCE
    assert 'Nenhum destino {destination} disponível; a lista permanece vazia.' in SOURCE


def test_bilibili_is_a_real_upload_destination_with_api_cards():
    assert '"Bilibili": "bilibili_api_cards"' in SOURCE
    assert '"Bilibili"' in SOURCE
    assert 'Enviar via bilibili-api (Python)' in SOURCE
    assert 'Configuração API > API Bilibili' in SOURCE


def test_social_auto_upload_cli_destinations_are_separate_and_optional():
    assert 'SAU_UPLOAD_DESTINATIONS = {' in SOURCE
    assert '"Douyin (social-auto-upload)": "douyin"' in SOURCE
    assert '"Bilibili (social-auto-upload)": "bilibili"' in SOURCE
    assert '"YouTube (social-auto-upload CLI)": "youtube"' in SOURCE
    assert 'raw_accounts = settings.get("sau_accounts", [])' in SOURCE
    assert 'Nenhuma conta deste destino foi adicionada; a lista permanece vazia' in SOURCE


def test_sau_upload_keeps_existing_youtube_and_tiktok_routes_separate():
    assert 'selected_youtube_channel = upload_targets.get("YouTube")' in SOURCE
    assert 'TikTok não é suportado pela CLI social-auto-upload' in SOURCE
    assert 'a integração TikTok existente do Thunderbolt continua disponível separadamente' in SOURCE
    assert 'upload_video_via_sau(' in SOURCE
