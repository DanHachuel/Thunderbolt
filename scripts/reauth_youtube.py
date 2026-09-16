"""Start a human-assisted Composio YouTube reauthorization flow.

The command never grants permissions silently: it prints a URL which a user must
open and approve in a browser. Existing connections are refreshed first; if the
refresh does not add the upload scope, a new link is requested.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.composio_upload import (
    YOUTUBE_UPLOAD_SCOPE,
    _client,
    _connected_account_id,
    _connected_account_details,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reautorizar uma conta YouTube do Composio para upload.")
    parser.add_argument("--account", required=True, help="Alias ou ID técnico da connected account.")
    parser.add_argument("--user-id", default=os.environ.get("COMPOSIO_USER_ID", ""), help="Composio user ID.")
    parser.add_argument("--api-key", default=os.environ.get("COMPOSIO_API_KEY", ""), help="Composio API key.")
    parser.add_argument("--auth-config-id", default=os.environ.get("COMPOSIO_YOUTUBE_AUTH_CONFIG_ID", ""), help="Auth config com o scope de upload.")
    args = parser.parse_args()
    client = _client(args.api_key)
    account_id = _connected_account_id(client, args.user_id, "youtube", args.account)
    accounts = client.connected_accounts
    try:
        accounts.refresh(connected_account_id=account_id)
        details = _connected_account_details(client, account_id)
        text = str(details)
        if YOUTUBE_UPLOAD_SCOPE in text:
            print(f"Scope de upload já presente na conta {account_id}.")
            return 0
    except Exception as exc:
        print(f"Refresh não concluiu a reautorização: {type(exc).__name__}: {exc}", file=sys.stderr)
    if not args.auth_config_id:
        print("Defina COMPOSIO_YOUTUBE_AUTH_CONFIG_ID com um auth config que inclua:")
        print(f"  {YOUTUBE_UPLOAD_SCOPE}")
        return 2
    link = accounts.link(
        user_id=args.user_id,
        auth_config_id=args.auth_config_id,
        alias=args.account,
    )
    redirect_url = getattr(link, "redirect_url", None) or (link.get("redirect_url") if isinstance(link, dict) else None)
    print("Abra este URL no navegador e conceda manualmente a permissão de upload:")
    print(redirect_url or link)
    print(f"Depois da autorização, confirme a conta com o ID técnico {account_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
