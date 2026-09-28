from io import BytesIO

import pandas as pd

from hermes_ui.channel_import import (
    CHANNEL_TEMPLATE_COLUMNS,
    build_channel_template_xlsx,
    channel_is_duplicate,
    parse_channel_workbook,
    resolve_blueprint,
    resolve_google_account,
    resolve_voice,
)


def _workbook_bytes(frame: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False)
    return output.getvalue()


def test_parse_spreadsheet_accepts_model_headers_and_semantic_values():
    frame = pd.DataFrame(
        [
            {
                "URL canal": "https://www.youtube.com/@FinancasClaras",
                "Nome canal": "Finanças Claras",
                "Handle canal": "FinancasClaras",
                "Narrador/ voz padrão": "pt-BR-FranciscaNeural-Female",
                "Idioma": "Português (Brasil)",
                "Nicho": "finanças",
                "Blueprint Padrão": "blueprint_finanças",
                "Estilo Wide": "Pexels e Pixabay",
                "Activo ": "sim",
                "Descrição": None,
                "Conta Google do Documento deste Canal": "owner@example.com",
                "Automação Ligada ": "não",
                "Horário diário (HH:MM)": "8:30",
                "DELEGATED_SESSION_ID": "session-123",
                "Duração Padrão Vídeos (Min)": 12,
            }
        ]
    )
    rows, warnings = parse_channel_workbook(_workbook_bytes(frame), "modelo.xlsx")
    assert not warnings
    assert len(rows) == 1
    row = rows[0]
    assert row["handle"] == "@FinancasClaras"
    assert row["active"] is True
    assert row["automation_on"] is False
    assert row["automation_time"] == "08:30"
    assert row["style_wide"] == "pexels"
    assert row["duration_minutes"] == 12


def test_semantic_catalog_resolution_treats_finance_names_as_same_blueprint():
    catalog = [("", "Sem Blueprint padrão"), ("blueprintcanalfinanças", "Blueprint Canal Finanças")]
    assert resolve_blueprint("finanças", catalog) == "blueprintcanalfinanças"
    assert resolve_blueprint("blueprint_finanças", catalog) == "blueprintcanalfinanças"
    assert resolve_blueprint("Blueprint Canal Finanças", catalog) == "blueprintcanalfinanças"


def test_legacy_finance_labels_resolve_to_renamed_seed_blueprint():
    catalog = [("", "Sem Blueprint padrão"), ("FINANCE USA", "FINANCE USA")]
    for value in ("finanças", "blueprint_finanças", "Blueprint Canal Finanças", "FINANCE"):
        assert resolve_blueprint(value, catalog) == "FINANCE USA"


def test_voice_and_google_account_resolution_accept_human_labels():
    assert resolve_voice("FranciscaNeural", ["", "pt-BR-FranciscaNeural-Female"]) == "pt-BR-FranciscaNeural-Female"
    assert resolve_google_account("owner@example.com", [{"id": "google_1", "email": "owner@example.com", "label": "Principal"}]) == (
        "google_1",
        "owner@example.com",
    )


def test_duplicate_detection_prefers_strong_channel_identity_and_falls_back_to_name():
    existing = {"name": "Finanças Claras", "handle": "@FinancasClaras", "url": "https://youtube.com/@FinancasClaras"}
    assert channel_is_duplicate({"name": "Outro nome", "handle": "@FinancasClaras", "url": ""}, existing)
    assert channel_is_duplicate({"name": "Finanças Claras", "handle": "", "url": ""}, existing)
    assert not channel_is_duplicate({"name": "Finanças Claras", "handle": "@OutroCanal", "url": ""}, existing)


def test_template_contains_all_public_model_columns_and_is_readable():
    content = build_channel_template_xlsx()
    frame = pd.read_excel(BytesIO(content), sheet_name="Canais YouTube")
    assert tuple(frame.columns) == CHANNEL_TEMPLATE_COLUMNS
    assert len(frame) == 20
