from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from hermes_ui import growth_tiktok

ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_analysis_code_has_stable_gta_pattern():
    code = growth_tiktok.analysis_code(datetime(2026, 9, 5, 19, 0, 0, tzinfo=timezone.utc))
    assert code.startswith("GTA-20260905-190000-")
    assert len(code) == len("GTA-20260905-190000-") + 6


def test_public_videos_limits_to_five_and_maps_engagement_fields():
    entries = [{"id": str(i), "title": f"Vídeo {i}", "view_count": i * 100, "like_count": i * 10} for i in range(10)]
    fake = Mock()
    fake.extract_info.return_value = {"entries": entries}
    fake.__enter__ = Mock(return_value=fake)
    fake.__exit__ = Mock(return_value=None)
    factory = Mock(return_value=fake)
    with patch.dict("sys.modules", {"yt_dlp": Mock(YoutubeDL=factory)}):
        result = growth_tiktok._public_videos("@conta")
    assert len(result) == 5
    assert result[2]["like_count"] == 20
    assert factory.call_args.args[0]["playlistend"] == 5


def test_report_contains_tiktok_metrics_and_private_data_limitation():
    record = {
        "code": "GTA-20260905-190000-ABC123", "channel_name": "Conta Teste",
        "created_at": "2026-09-05T19:00:00+00:00", "overall_score": 62,
        "monetization_status": "A verificar — faltam dados privados", "sample_views": 1200,
        "profile": {"subscriber_count": 300},
        "metrics": [{"label": "Engajamento", "score": 70, "value": "5.0% na amostra", "diagnosis": "Bom"}],
        "videos": [{"title": "Hook | teste", "view_count": 1200, "like_count": 80, "comment_count": 4, "duration": 62}],
    }
    report = growth_tiktok._report_markdown(record)
    assert "TIKTOK CHANNEL AUDIT REPORT: Conta Teste" in report
    assert "Engajamento" in report
    assert "Hook / teste" in report
    assert "TikTok Studio" in report


def test_growth_tiktok_route_uses_real_renderer():
    # Commit 560d696 ("reorganizar abas de growth") renomeou a rota
    # "Analista Growth Tiktok" para "Growth Tiktok", mantendo o nome antigo
    # como alias; o renderer real continua ligado e sem placeholder.
    assert '"Analista Growth Tiktok": "Growth Tiktok"' in MAIN_SOURCE
    assert '"Growth Tiktok": render_growth_tiktok' in MAIN_SOURCE
    assert "render_edit_placeholder(\"Analista Growth Tiktok\"" not in MAIN_SOURCE


def test_run_audit_uses_public_profile_and_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_tiktok, "ANALYSES_DIR", tmp_path / "growth")
    monkeypatch.setattr(growth_tiktok, "read_json", lambda _name, default: default)
    saved = {}
    monkeypatch.setattr(growth_tiktok, "write_json", lambda name, value: saved.update({name: value}))
    profile = Mock(ok=True, data={"name": "Conta", "subscriber_count": 12000})
    with patch.object(growth_tiktok, "fetch_public_tiktok_profile", return_value=profile), patch.object(growth_tiktok, "_public_videos", return_value=[{"id": "1", "title": "Teste", "view_count": 1000, "like_count": 80, "comment_count": 10, "repost_count": 5, "duration": 65}]):
        record = growth_tiktok.run_audit({"id": "t1", "name": "Conta", "url": "https://www.tiktok.com/@conta"})
    assert record["platform"] == "TikTok"
    assert record["report_path"].endswith(".md")
    assert record["sample_views"] == 1000
    assert "tiktok_growth_analyses.json" in saved
