"""Login falso positivo corrigido + multi-plataforma/multi-conta com proxy binding (1.0.29).

O login visível do YouTube anunciava «Login validado» de um browser que abria
e fechava sem login: a detecção por URL («studio.youtube.com in page.url»)
disparava logo após o goto (o alvo É studio) e a validação aceitava cookies
de visitante. Agora: só os COOKIES ESSENCIAIS (SID/HSID/SSID) provam
autenticação — no browser vivo e no storage_state gravado; «Sem proxy» por
conta = ligação DIRECTA explícita; login e upload da mesma conta saem pelo
mesmo proxy.
"""
from __future__ import annotations

import json

import pytest

from hermes_ui import social_auto_upload_backend as backend
from hermes_ui import storage


def _storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "STORAGE", root)
    monkeypatch.setattr(storage, "STATE", root / "state")
    monkeypatch.setattr(storage, "BLUEPRINTS", root / "blueprints")
    monkeypatch.setattr(storage, "TIKTOK_PROMPT_MASTERS", root / "tiktok" / "prompts_master")
    monkeypatch.setattr(storage, "MEDIA_DOWNLOADS", root / "media_downloads")
    monkeypatch.setattr(storage, "NICHES_DATA", root / "data" / "niches")
    storage.ensure_storage()
    return root


# ---------------------------------------------------------------------------
# 1. Falso positivo: o login só é válido com os cookies ESSENCIAIS
# ---------------------------------------------------------------------------


class _FakePage:
    def __init__(self, url="https://studio.youtube.com/"):
        self.url = url

    def is_closed(self):
        return False

    def goto(self, *args, **kwargs):
        return None


class _FakeContext:
    def __init__(self, cookies):
        self._cookies = list(cookies)

    def cookies(self):
        return [dict(cookie) for cookie in self._cookies]

    def storage_state(self, path=None, **kwargs):
        payload = {"cookies": [dict(cookie) for cookie in self._cookies]}
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        return payload

    def new_page(self):
        return _FakePage()

    def close(self):
        return None


class _FakeBrowser:
    def __init__(self, context):
        self._context = context

    def new_context(self):
        return self._context

    def close(self):
        return None


def _visitor_youtube_cookies():
    return [
        {"name": "VISITOR_INFO1_LIVE", "value": "visitor-token", "domain": ".youtube.com"},
        {"name": "YSC", "value": "y", "domain": ".youtube.com"},
    ]


def _authenticated_youtube_cookies():
    return _visitor_youtube_cookies() + [
        {"name": "SID", "value": "sid-value", "domain": ".youtube.com"},
        {"name": "HSID", "value": "hsid-value", "domain": ".youtube.com"},
        {"name": "SSID", "value": "ssid-value", "domain": ".youtube.com"},
    ]


def test_visitor_only_storage_state_is_rejected_as_failed_login():
    """E2E passo 1: fechar o browser antes da senha → ERRO, nunca sucesso."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        state = Path(folder) / "storage_state.json"
        state.write_text(json.dumps({"cookies": _visitor_youtube_cookies()}), encoding="utf-8")
        valid, message = backend.validate_storage_state(state, "youtube.com")
        assert valid is False
        assert "O login falhou ou foi cancelado. Tente novamente." in message


def test_login_youtube_never_succeeds_without_essential_cookies(tmp_path, monkeypatch):
    """O browser abre em studio (o alvo) com cookies de visitante: o loop de
    cookies essenciais NUNCA autentica e o login devolve falha — o falso
    positivo (sucesso imediato pós-goto por URL) morre aqui."""
    _storage(tmp_path, monkeypatch)
    # o CI corre headless: estes testes validam o fluxo de login, não a GUI
    monkeypatch.setattr(backend, "has_gui_environment", lambda: True)
    context = _FakeContext(_visitor_youtube_cookies())
    monkeypatch.setattr(backend, "launch_browser", lambda *args, **kwargs: _FakeBrowser(context))
    result = backend.login_youtube_session(timeout_seconds=1)
    assert result["success"] is False
    # falha por timeout de cookies essenciais — nunca «Login validado»
    assert result["status"] == "timeout"
    assert "O login não foi concluído" in result["message"]
    # nenhuma sessão parcial foi guardada
    assert backend.has_valid_youtube_session() is False


def test_login_youtube_succeeds_only_after_real_authentication(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    monkeypatch.setattr(backend, "has_gui_environment", lambda: True)
    context = _FakeContext(_authenticated_youtube_cookies())
    monkeypatch.setattr(backend, "launch_browser", lambda *args, **kwargs: _FakeBrowser(context))
    result = backend.login_youtube_session(timeout_seconds=5)
    assert result["success"] is True
    assert result["message"] == "Login validado e sessão guardada localmente."
    assert backend.has_valid_youtube_session() is True


# ---------------------------------------------------------------------------
# 2. Multi-plataforma: registo + login visível por conta no formato da CLI
# ---------------------------------------------------------------------------


def test_platform_login_targets_cover_youtube_tiktok_douyin_bilibili():
    for platform in ("youtube", "tiktok", "douyin", "bilibili", "instagram"):
        target = backend.platform_login_target(platform)
        assert target["url"], platform
        assert target["domain"], platform
    assert backend.platform_login_target("youtube")["essential"] == ("SID", "HSID", "SSID")
    assert backend.platform_login_target("plataforma_x") == {"url": "", "domain": "", "essential": ()}


def test_add_sau_account_stores_the_bound_proxy(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    account = backend.add_sau_account("youtube", "yt_principal", "YT Principal", proxy_id="proxy_us")
    assert account["proxy_id"] == "proxy_us"
    assert backend.get_sau_account("youtube", "yt_principal")["proxy_id"] == "proxy_us"
    # segunda conta com proxy diferente — multi-conta com proxies distintos
    backend.add_sau_account("tiktok", "tiktok_secundario", "TikTok Secundário", proxy_id="")
    listed = backend.list_sau_accounts()
    assert len(listed) == 2
    assert {(item["platform"], item["proxy_id"]) for item in listed} == {("youtube", "proxy_us"), ("tiktok", "")}


def test_set_sau_account_proxy_updates_the_binding(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    backend.add_sau_account("douyin", "canal", "Canal")
    assert backend.set_sau_account_proxy("douyin", "canal", "proxy_br")["proxy_id"] == "proxy_br"
    assert backend.sau_account_proxy_id("douyin", "canal") == "proxy_br"
    backend.set_sau_account_proxy("douyin", "canal", "")
    assert backend.sau_account_proxy_id("douyin", "canal") == ""


def test_login_social_account_uses_the_account_proxy_and_cli_cookie_path(tmp_path, monkeypatch):
    """E2E passo 2: YT Principal com «Proxy US», TikTok com «Sem proxy» — o
    login de cada conta abre o browser com o proxy ASSOCIADO e grava o cookie
    no caminho/formato da CLI (cookies/<plataforma>_<conta>.json)."""
    _storage(tmp_path, monkeypatch)
    monkeypatch.setattr(backend, "has_gui_environment", lambda: True)
    backend.add_sau_account("youtube", "yt_principal", "YT Principal", proxy_id="proxy_us")
    backend.add_sau_account("tiktok", "tiktok_secundario", "TikTok Secundário", proxy_id="")
    launched = {}

    def fake_launch_browser(browser_type, **kwargs):
        launched["proxy"] = kwargs.get("proxy")
        launched["browser_type"] = browser_type
        cookies = _authenticated_youtube_cookies() if launched["count"] == 0 else [
            {"name": "sessionid", "value": "tt-session", "domain": ".tiktok.com"},
        ]
        return _FakeBrowser(_FakeContext(cookies))

    launched["count"] = 0
    original = fake_launch_browser

    def counting_launch(browser_type, **kwargs):
        result = original(browser_type, **kwargs)
        launched["count"] += 1
        return result

    monkeypatch.setattr(backend, "launch_browser", counting_launch)
    monkeypatch.setattr(
        backend, "get_proxy_for_browser",
        lambda proxy_id: {"server": "us.example:8080", "scheme": "http", "username": "u", "password": "p"} if proxy_id == "proxy_us" else None,
    )

    yt = backend.login_social_account("youtube", "yt_principal", timeout_seconds=3)
    assert yt["success"] is True
    assert yt["cookie_path"].endswith("youtube_yt_principal.json")
    assert yt["proxy_id"] == "proxy_us"
    assert launched["proxy"] is not None  # o YT usou o proxy da conta

    tiktok = backend.login_social_account("tiktok", "tiktok_secundario", timeout_seconds=3)
    assert tiktok["success"] is True
    assert tiktok["cookie_path"].endswith("tiktok_tiktok_secundario.json")
    assert tiktok["proxy_id"] == ""
    assert launched["proxy"] is None  # «Sem proxy» = ligação DIRECTA explícita


def test_login_social_account_without_essential_cookies_fails(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    monkeypatch.setattr(backend, "has_gui_environment", lambda: True)
    backend.add_sau_account("douyin", "canal", "Canal")
    monkeypatch.setattr(
        backend, "launch_browser",
        lambda *args, **kwargs: _FakeBrowser(_FakeContext([{"name": "ttwid", "value": "visitante", "domain": ".douyin.com"}])),
    )
    result = backend.login_social_account("douyin", "canal", timeout_seconds=1)
    assert result["success"] is False
    assert result["status"] == "timeout"
    assert "O login não foi concluído" in result["message"]


# ---------------------------------------------------------------------------
# 3. Proxy binding no upload: o conf da CLI recebe o proxy da CONTA
# ---------------------------------------------------------------------------


def test_runtime_conf_carries_the_account_proxy(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    monkeypatch.setattr(
        backend, "get_proxy_for_browser",
        lambda proxy_id: {"server": "us.example:8080", "scheme": "http", "username": "u", "password": "p"} if proxy_id == "proxy_us" else None,
    )
    env, runtime = backend._sau_environment("proxy_us")
    conf = (runtime / "conf.py").read_text(encoding="utf-8")
    assert "YT_PROXY = 'http://u:p@us.example:8080'" in conf

    env_direct, runtime_direct = backend._sau_environment(None)
    conf_direct = (runtime_direct / "conf.py").read_text(encoding="utf-8")
    assert "YT_PROXY = None" in conf_direct


def test_login_platform_passes_the_account_proxy_to_the_cli_env(tmp_path, monkeypatch):
    _storage(tmp_path, monkeypatch)
    backend.add_sau_account("youtube", "conta", "Conta", proxy_id="proxy_us")
    captured = {}
    monkeypatch.setattr(backend, "get_sau_install_status", lambda: {"installed": True, "status": "installed", "message": "ok", "python": "3.11"})
    monkeypatch.setattr(backend, "_write_sau_runtime_config", lambda proxy_url=None: captured.setdefault("proxy_url", proxy_url) or (tmp_path / "runtime"))
    monkeypatch.setattr(
        backend, "get_proxy_for_browser",
        lambda proxy_id: {"server": "us.example:8080", "scheme": "http", "username": "u", "password": "p"} if proxy_id == "proxy_us" else None,
    )
    monkeypatch.setattr(backend, "_run_sau_cli", lambda args, timeout_seconds=30: {"status": "error", "message": "cli fechada"})
    monkeypatch.setattr(backend, "has_gui_environment", lambda: True)
    backend.login_platform("youtube", "conta", timeout_seconds=5)
    assert captured["proxy_url"] == "http://u:p@us.example:8080"


def test_upload_youtube_video_rejects_visitor_only_session(tmp_path, monkeypatch):
    """O upload directo (Rota A) NUNCA sobe com uma sessão de visitante — a
    validação essencial também protege o pipeline, não só a UI."""
    _storage(tmp_path, monkeypatch)
    state_file = backend.session_state_path()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"cookies": _visitor_youtube_cookies()}), encoding="utf-8")
    result = backend.upload_youtube_video(task_id="t1", video_path="nao_existe.mp4", title="T")
    assert result.ok is False
    assert "O login falhou ou foi cancelado. Tente novamente." in result.message
