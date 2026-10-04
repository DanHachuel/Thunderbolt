from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_social_auto_upload_storage_is_ignored_by_npm_pack_dry_run():
    # No Windows "npm" é um .cmd que o CreateProcess não resolve pelo nome;
    # shutil.which devolve o executável absoluto em todas as plataformas. Em
    # Windows pedir primeiro npm.cmd — a pasta do node inclui também um script
    # sh chamado "npm" que não captura stdout quando invocado pelo CreateProcess.
    npm_executable = (shutil.which("npm.cmd") if sys.platform == "win32" else None) or shutil.which("npm")
    if npm_executable is None:
        pytest.skip("npm não encontrado no PATH deste ambiente; a verificação de empacotamento não pode correr aqui.")
    private_dir = ROOT / "storage" / "state" / "social_auto_upload"
    created_dirs: list[Path] = []
    current = private_dir
    while not current.exists():
        created_dirs.append(current)
        current = current.parent
    private_dir.mkdir(parents=True, exist_ok=True)
    sentinel = private_dir / f"npm-pack-sentinel-{uuid.uuid4().hex}.json"
    sentinel.write_text('{"private":"session"}\n', encoding="utf-8")
    try:
        completed = subprocess.run(
            [npm_executable, "pack", "--dry-run", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            # O npm emite UTF-8; sem isto o Windows decodifica com cp1252 e o
            # thread de leitura do stdout falha (stdout=None).
            encoding="utf-8",
            timeout=180,
            check=True,
        )
        payload = json.loads(completed.stdout)
        # npm <=11 emite uma lista de pacotes; npm 12 emite um objecto indexado
        # pelo nome do pacote. Normalizar para os dois formatos.
        packages = list(payload.values()) if isinstance(payload, dict) else payload
        files = [str(item.get("path") or "").replace("\\", "/") for package in packages for item in package.get("files", [])]
        assert "app/social_auto_upload_ui.py" in files
        assert not any(path == "storage" or path.startswith("storage/") for path in files)
        assert not any(sentinel.name in path for path in files)
    finally:
        sentinel.unlink(missing_ok=True)
        for directory in created_dirs:
            try:
                directory.rmdir()
            except OSError:
                break
