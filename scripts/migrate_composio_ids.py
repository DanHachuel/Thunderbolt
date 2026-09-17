"""Migrate YouTube channels from name aliases to real Composio IDs."""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

from integrations.composio_account_resolver import candidate_message, discover_connected_account
from integrations.composio_upload import _client
from hermes_ui.storage import STATE, read_json, update_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default="", help="Composio API key; defaults to settings.json")
    args = parser.parse_args()
    settings = read_json("settings.json", {})
    api_key = str(args.api_key or settings.get("composio_api_key") or "").strip()
    if not api_key:
        print("Composio API key não configurada; nenhuma migração foi executada.")
        return 1
    channels = [item for item in read_json("channels.json", []) if isinstance(item, dict)]
    backup = STATE / f"channels.json.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if not backup.exists():
        shutil.copy2(STATE / "channels.json", backup)
    client = _client(api_key)
    migrated = already = failed = 0
    for channel in channels:
        nested = channel.get("composio") if isinstance(channel.get("composio"), dict) else {}
        if str(nested.get("connected_account_id") or "").startswith("ca_"):
            already += 1
            continue
        try:
            resolved = discover_connected_account(client, str(channel.get("name") or ""), channel_id_youtube=str(channel.get("youtube_channel_id") or ""))
            if not resolved:
                print(f"{channel.get('name') or 'Canal'}: {candidate_message([])}")
                failed += 1
                continue
            channel["composio"] = {key: value for key, value in resolved.items() if key != "candidates"}
            channel["composio_connected_account_id"] = resolved["connected_account_id"]
            migrated += 1
        except Exception as exc:
            print(f"{channel.get('name') or 'Canal'}: {type(exc).__name__}: {exc}")
            failed += 1

    def replace(current):
        if isinstance(current, list):
            current[:] = channels
        return current

    update_json("channels.json", [], replace)
    print(f"Migração concluída: {migrated} migrados, {already} já válidos, {failed} falhas. Backup: {backup}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
