from __future__ import annotations

import importlib.util
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "seed" / "skills" / "mpt_agent.py"
SPEC = importlib.util.spec_from_file_location("test_mpt_agent", MODULE_PATH)
assert SPEC and SPEC.loader
mpt_agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mpt_agent)


class PexelsFixtureHandler(BaseHTTPRequestHandler):
    status = 200
    body = b'{"collections": []}'
    delay = 0.0
    cut_connection = False

    def do_GET(self):
        if self.delay:
            time.sleep(self.delay)
        if self.cut_connection:
            self.connection.close()
            return
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args):
        return


@pytest.fixture
def pexels_fixture(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), PexelsFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(mpt_agent, "PEXELS_VALIDATION_URL", f"http://127.0.0.1:{server.server_port}/v1/collections")
    yield PexelsFixtureHandler
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


@pytest.mark.parametrize("status", [401, 403, 429])
def test_pexels_rejects_auth_and_rate_limit_responses(pexels_fixture, status):
    pexels_fixture.status = status
    assert mpt_agent._validate_pexels_key("x" * 32) == "rejected"


@pytest.mark.parametrize("status,body", [(200, b'{"collections": []}'), (200, b'')])
def test_pexels_accepts_successful_responses_including_empty_collection(pexels_fixture, status, body):
    pexels_fixture.status = status
    pexels_fixture.body = body
    assert mpt_agent._validate_pexels_key("x" * 32) == "valid"


@pytest.mark.parametrize("status", [500, 502])
def test_pexels_keeps_configuration_on_server_errors(pexels_fixture, status):
    pexels_fixture.status = status
    assert mpt_agent._validate_pexels_key("x" * 32) == "unknown"


def test_pexels_timeout_and_cut_connection_are_unknown(pexels_fixture):
    pexels_fixture.delay = 16
    assert mpt_agent._validate_pexels_key("x" * 32) == "unknown"
    pexels_fixture.delay = 0
    pexels_fixture.cut_connection = True
    assert mpt_agent._validate_pexels_key("x" * 32) == "unknown"
