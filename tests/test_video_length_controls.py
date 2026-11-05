from pathlib import Path

from hermes_ui.video_length import DEFAULT_AVERAGE_VIDEO_TIME, channel_video_length, channel_video_time_value, explicit_word_count, length_generation_settings, words_from_channel_time


MAIN_SOURCE = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")


def test_blueprint_character_range_never_defines_the_target():
    """1.0.61 - REGRA INVIOLAVEL (AGENTS.md): o canal e a UNICA fonte de verdade.

    Ate a 1.0.60 um canal sem tempo caia na range de caracteres do BLUEPRINT
    (1333 palavras = metade de um video de 20 min) - era essa a origem real do
    relato "os videos saem com o tamanho errado, a LLM obedece ao Blueprint".
    A partir daqui o blueprint NUNCA define o tamanho: o canal assume o padrao
    da plataforma (20:00).
    """
    words, duration, source = channel_video_length({}, {"strict_character_range": [7000, 9000]})
    assert (words, duration, source) == (3000, "20:00", "padrão do canal")
    # ... mesmo quando o canal tem o tempo explicitamente vazio ou 00:00.
    for empty in ({"average_video_time": ""}, {"average_video_time": "00:00"}, {"average_video_time": None}):
        words, duration, source = channel_video_length(empty, {"strict_character_range": [7000, 9000]})
        assert (words, duration, source) == (3000, "20:00", "padrão do canal"), empty


def test_explicit_word_count_stays_a_diagnostic_reference_only():
    """A conversao blueprint->palavras continua existindo para a UI MOSTRAR a
    referencia - mas nunca entra no alvo do canal."""
    assert explicit_word_count({"strict_character_range": [7000, 9000]}) == 1333
    assert explicit_word_count({}, "Escreva aproximadamente 600 palavras por roteiro.") == 600


def test_channel_time_overrides_blueprint_reference():
    settings = length_generation_settings({"average_video_time": "02:00"}, {"word_count": 2400})
    assert settings["target_word_count"] == 300
    assert settings["target_video_duration"] == "02:00"
    assert settings["target_word_count_source"] == "canal"


def test_zero_channel_time_assumes_the_platform_default():
    """1.0.61 - canal com 00:00 ASSUME 20:00 (o Prompt Master nao manda no tamanho)."""
    prompt = "Escreva aproximadamente 600 palavras por roteiro."
    assert explicit_word_count({}, prompt) == 600
    words, duration, source = channel_video_length({"average_video_time": "00:00"}, {}, prompt)
    assert (words, duration, source) == (3000, "20:00", "padrão do canal")


def test_tiktok_channel_keeps_its_short_platform_default():
    """A excepcao de proposito: canais TikTok mantem o padrao curto da plataforma
    (01:20) - o default global de 20:00 e para o YouTube/longa-forma."""
    words, duration, source = channel_video_length({"platform": "tiktok"}, {"word_count": 900})
    assert (words, duration, source) == (200, "01:20", "padrão do canal")


def test_empty_channel_uses_twenty_minute_default():
    assert DEFAULT_AVERAGE_VIDEO_TIME == "20:00"
    assert channel_video_length({}, {}, "") == (3000, "20:00", "padrão do canal")


def test_channel_duration_uses_minutes_and_seconds():
    assert words_from_channel_time("12:00") == 1800
    assert words_from_channel_time("00:12") == 30


def test_legacy_default_is_migrated_without_changing_explicit_seconds():
    assert channel_video_time_value({"average_video_time": "00:12"}) == "20:00"
    assert channel_video_time_value({"average_video_time": "00:12", "average_video_word_count": 30}) == "00:12"
    assert channel_video_length({"average_video_time": "00:12"}, {}, "") == (3000, "20:00", "canal")


def test_channel_cards_have_average_time_and_refresh_controls():
    assert 'Tempo Medio de Video' in MAIN_SOURCE
    assert MAIN_SOURCE.count('Tempo Medio de Video') >= 4
    assert 'Tempo Medio de Video (HH:MM)' not in MAIN_SOURCE
    assert 'DEFAULT_AVERAGE_VIDEO_TIME' in MAIN_SOURCE
    assert MAIN_SOURCE.count('Guardar tempo') >= 1
    assert 'youtube_channel_average_video_time_' in MAIN_SOURCE
    assert 'tiktok_channel_average_video_time_' in MAIN_SOURCE
    assert 'refresh_youtube_metrics_' in MAIN_SOURCE
    assert 'refresh_tiktok_metrics_' in MAIN_SOURCE
    assert 'length_generation_settings' in MAIN_SOURCE
