from types import SimpleNamespace

import pytest

from integrations.composio_account_resolver import AccountDiscoveryError, discover_connected_account, normalize_channel_name


def test_normalize_channel_name_handles_accents_separators_and_symbols():
    assert normalize_channel_name(" Educação__Financeira! ") == "educacao financeira"


def test_discover_uses_account_user_id_and_connected_account_id():
    calls = []

    class Accounts:
        def list(self, **kwargs):
            assert kwargs == {"toolkit_slugs": ["youtube"]}
            return SimpleNamespace(items=[SimpleNamespace(id="ca_real_1", user_id="composio-user-real")])

    class Tools:
        def execute(self, **kwargs):
            calls.append(kwargs)
            return {"data": {"items": [{"id": "UC123", "snippet": {"title": "Brick by Brick Wealth"}}]}}

    result = discover_connected_account(SimpleNamespace(connected_accounts=Accounts(), tools=Tools()), "Brick-by-Brick-Wealth")
    assert result["connected_account_id"] == "ca_real_1"
    assert result["user_id"] == "composio-user-real"
    assert calls[0]["connected_account_id"] == "ca_real_1"
    assert calls[0]["user_id"] == "composio-user-real"
    assert calls[0]["dangerously_skip_version_check"] is True


def test_discover_returns_none_when_channel_is_missing():
    class Accounts:
        def list(self, **kwargs):
            return {"items": [{"id": "ca_1", "user_id": "user-1"}]}

    class Tools:
        def execute(self, **kwargs):
            return {"data": {"items": []}}

    assert discover_connected_account(SimpleNamespace(connected_accounts=Accounts(), tools=Tools()), "Deleted Channel") is None


def test_discover_rejects_ambiguous_matching_channels():
    class Accounts:
        def list(self, **kwargs):
            return {"items": [
                {"id": "ca_1", "user_id": "user-1"},
                {"id": "ca_2", "user_id": "user-2"},
            ]}

    class Tools:
        def execute(self, **kwargs):
            return {"data": {"items": [{"id": kwargs["connected_account_id"], "snippet": {"title": "DAN-HACHUEL"}}]}}

    with pytest.raises(AccountDiscoveryError) as error:
        discover_connected_account(SimpleNamespace(connected_accounts=Accounts(), tools=Tools()), "Dan Hachuel")
    assert len(error.value.candidates) == 2
