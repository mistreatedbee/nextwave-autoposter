#!/usr/bin/env python3
"""One-time helper: turn a short-lived Graph API Explorer token into a Page token for .env.

A Page token derived from a long-lived user token does not expire.
Secrets are typed with hidden input and only masked values are printed.
"""
from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent / ".env"
VERSION = os.environ.get("GRAPH_API_VERSION") or "v26.0"
BASE = f"https://graph.facebook.com/{VERSION}"


def mask(value: str) -> str:
    return value if len(value) <= 8 else f"{value[:4]}…{value[-4:]} ({len(value)} chars)"


def graph_get(path: str, params: dict, secrets: list[str]) -> dict:
    try:
        resp = requests.get(f"{BASE}/{path}", params=params, timeout=30)
        body = resp.json()
    except (requests.RequestException, ValueError) as e:
        msg = str(e)
        for s in secrets:
            msg = msg.replace(s, "***")
        sys.exit(f"Request failed: {msg}")
    if resp.status_code >= 400 or "error" in body:
        err = body.get("error", {})
        sys.exit(f"Meta said no (code {err.get('code')}): {err.get('message', resp.status_code)}")
    return body


def write_env(values: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    kept = [ln for ln in lines if ln.split("=", 1)[0].strip() not in values]
    kept += [f"{k}={v}" for k, v in values.items()]
    ENV_PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")
    ENV_PATH.chmod(0o600)


def main() -> None:
    print("Paste values from developers.facebook.com. Secret input is hidden.\n")
    app_id = input("App ID: ").strip()
    app_secret = getpass("App Secret (hidden): ").strip()
    short = getpass("Short-lived user token from Graph API Explorer (hidden): ").strip()
    secrets = [app_secret, short]

    long_lived = graph_get("oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": app_secret, "fb_exchange_token": short}, secrets)["access_token"]
    secrets.append(long_lived)
    print("Exchanged for a long-lived user token.")

    pages = graph_get("me/accounts", {
        "fields": "id,name,access_token,instagram_business_account{id,username}",
        "access_token": long_lived}, secrets).get("data", [])
    if not pages:
        sys.exit("No Pages found. Make sure you ticked your Page when granting permissions "
                 "and that pages_show_list was selected.")
    print("\nPages you manage:")
    for i, p in enumerate(pages, 1):
        ig = p.get("instagram_business_account")
        print(f"  {i}. {p['name']} (id {p['id']}) - Instagram: "
              + (f"@{ig['username']}" if ig else "NOT LINKED"))
    choice = 1 if len(pages) == 1 else int(input("Choose a Page number: ") or 0)
    if not 1 <= choice <= len(pages):
        sys.exit("Invalid choice.")
    page = pages[choice - 1]
    ig = page.get("instagram_business_account")

    values = {"META_PAGE_ID": page["id"], "META_PAGE_TOKEN": page["access_token"]}
    if ig:
        values["META_IG_USER_ID"] = ig["id"]
    else:
        print("WARNING: no Instagram Business/Creator account is linked to this Page; "
              "Instagram posting will not work until it is.")
    write_env(values)
    print(f"\nSaved to {ENV_PATH.name} (permissions 600):")
    for k, v in values.items():
        print(f"  {k}={mask(v)}")
    print("\nNext: python3 post.py check")


if __name__ == "__main__":
    main()
