from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from hermes_ui import growth_instagram

ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_analysis_code_has_stable_gia_pattern():
    code = growth_instagram.analysis_code(datetime(2026, 9, 5, 19, 0, 0, tzinfo=timezone.utc))
    assert code.startswith("GIA-20260905-190000-")
    assert len(code) == len("GIA-20260905-190000-") + 6


def test_public_posts_limits_to_five_and_maps_instagram_fields():
    entries = [{"id": str(i), "title": f"Post {i}", "view_count": i * 100, "like_count": i * 10, "save_count": i} for i in range(10)]
    fake = Mock()
    fake.extract_info.return_value = {"entries": entries}
    fake.__enter__ = Mock(return_value=fake)
    fake.__exit__ = Mock(return_value=None)
    factory = Mock(return_value=fake)
    with patch.dict("sys.modules", {"yt_dlp": Mock(YoutubeDL=factory)}):
        result = growth_instagram._public_videos("@conta")
    assert len(result) == 5
    assert result[2]["save_count"] == 2
    assert factory.call_args.args[0]["playlistend"] == 5


def test_report_contains_instagram_metrics_and_insights_limitation():
    record = {
        "code": "GIA-20260905-190000-ABC123", "channel_name": "Conta Teste",
        "created_at": "2026-09-05T19:00:00+00:00", "overall_score": 62,
        "monetization_status": "A verificar — faltam dados privados", "sample_views": 1200,
        "profile": {"subscriber_count": 300},
        "metrics": [{"label": "Engajamento e saves", "score": 70, "value": "5.0% na amostra", "diagnosis": "Bom"}],
        "videos": [{"title": "Hook | teste", "view_count": 1200, "like_count": 80, "comment_count": 4, "duration": 32}],
    }
    report = growth_instagram._report_markdown(record)
    assert "INSTAGRAM CHANNEL AUDIT REPORT: Conta Teste" in report
    assert "Engajamento e saves" in report
    assert "Hook / teste" in report
    assert "Instagram Insights" in report


def test_run_audit_uses_public_profile_and_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_instagram, "ANALYSES_DIR", tmp_path / "growth")
    monkeypatch.setattr(growth_instagram, "read_json", lambda _name, default: default)
    saved = {}
    monkeypatch.setattr(growth_instagram, "write_json", lambda name, value: saved.update({name: value}))
    profile = Mock(ok=True, data={"name": "Conta", "subscriber_count": 12000})
    with patch.object(growth_instagram, "fetch_public_instagram_profile", return_value=profile), patch.object(growth_instagram, "_public_videos", return_value=[{"id": "1", "title": "Teste", "view_count": 1000, "like_count": 80, "comment_count": 10, "repost_count": 5, "save_count": 20, "duration": 32}]):
        record = growth_instagram.run_audit({"id": "i1", "name": "Conta", "url": "https://www.instagram.com/conta/"})
    assert record["platform"] == "Instagram"
    assert record["report_path"].endswith(".md")
    assert record["sample_views"] == 1000
    assert "instagram_growth_analyses.json" in saved


def test_growth_instagram_route_and_platform_classifier_are_wired():
    # Commit 560d696 ("reorganizar abas de growth") renomeou a rota
    # "Analista Growth Instagram" para "Growth Instagram", mantendo o nome
    # antigo como alias; renderer real e classificador de plataforma continuam
    # ligados, sem placeholder.
    assert '"Analista Growth Instagram": "Growth Instagram"' in MAIN_SOURCE
    assert '"Growth Instagram": render_growth_instagram' in MAIN_SOURCE
    assert 'if value in {"instagram", "ig"}:' in MAIN_SOURCE
    assert 'render_edit_placeholder("Analista Growth Instagram"' not in MAIN_SOURCE
