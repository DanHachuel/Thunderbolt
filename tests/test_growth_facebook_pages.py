from datetime import datetime, timezone
from pathlib import Path

from hermes_ui import growth_facebook_pages

ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_analysis_code_has_stable_gfa_pattern():
    code = growth_facebook_pages.analysis_code(datetime(2026, 9, 5, 19, 0, 0, tzinfo=timezone.utc))
    assert code.startswith("GFA-20260905-190000-")
    assert len(code) == len("GFA-20260905-190000-") + 6


def test_report_uses_facebook_pages_metrics_and_insights_limitation():
    report = growth_facebook_pages._report_markdown({
        "code": "GFA-20260905-190000-ABC123", "page_name": "Página Teste",
        "created_at": "2026-09-05T19:00:00+00:00", "overall_score": 62,
        "metrics": [{"label": "Qualidade da thumbnail", "score": 50, "value": "CTR indisponível", "diagnosis": "Requer Creator Studio"}],
        "posts": [{"title": "Hook | teste", "view_count": 1000, "like_count": 80, "comment_count": 4, "share_count": 12}],
    })
    assert "FACEBOOK GROWTH AUDIT REPORT: Página Teste" in report
    assert "Qualidade da thumbnail" in report
    assert "Hook / teste" in report
    assert "Page Insights" in report


def test_run_audit_uses_local_public_posts_and_persists_report(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_facebook_pages, "ANALYSES_DIR", tmp_path / "growth")
    monkeypatch.setattr(growth_facebook_pages, "read_json", lambda _name, default: default)
    saved = {}
    monkeypatch.setattr(growth_facebook_pages, "write_json", lambda name, value: saved.update({name: value}))
    page = {"id": "p1", "name": "Página", "followers": 12000, "posts": [{"title": "Post", "views": 1000, "reactions": 80, "comments": 10, "shares": 5}]}
    record = growth_facebook_pages.run_audit(page)
    assert record["platform"] == "Facebook Pages"
    assert record["sample_views"] == 1000
    assert record["report_path"].endswith(".md")
    assert "facebook_pages_growth_analyses.json" in saved


def test_growth_facebook_route_is_real_renderer():
    # Commit 560d696 ("reorganizar abas de growth") renomeou a rota
    # "Analista Facebook Pages" para "Facebook Pages", mantendo o nome antigo
    # como alias; o renderer real continua ligado e sem placeholder.
    assert '"Analista Facebook Pages": "Facebook Pages"' in MAIN_SOURCE
    assert '"Facebook Pages": render_growth_facebook_pages' in MAIN_SOURCE
    assert 'render_edit_placeholder("Analista Facebook Pages"' not in MAIN_SOURCE
    assert 'render_edit_placeholder("Facebook Pages"' not in MAIN_SOURCE
