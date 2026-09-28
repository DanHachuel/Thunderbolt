from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_social_auto_upload_session_directory_is_explicitly_gitignored():
    ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8").replace("\\", "/")
    assert "storage/state/social_auto_upload/" in ignore_text
