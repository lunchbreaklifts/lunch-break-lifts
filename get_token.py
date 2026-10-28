#!/usr/bin/env python3
"""
One-time helper: checks the access token you generated in the Meta app dashboard
and prints the Instagram account ID that publish.py needs.

Run it on your own computer. Nothing is saved. The token input is hidden.

Usage:
    python get_token.py
"""

import getpass
import json
import sys
from pathlib import Path

import requests

CONFIG = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
API = f"https://graph.instagram.com/{CONFIG.get('instagram_api_version', 'v23.0')}"


def main():
    print("Paste the access token from your Meta app dashboard:")
    print("  App dashboard > Instagram > API setup with Instagram login >")
    print("  Generate access tokens > Generate token (for lunch_breaklifts)\n")
    token = getpass.getpass("Access token (hidden): ").strip()

    r = requests.get(f"{API}/me", params={"fields": "user_id,username,account_type", "access_token": token}, timeout=60)
    data = r.json()
    if "error" in data:
        sys.exit(f"Instagram API error: {data['error'].get('message', data['error'])}")

    print("\n" + "=" * 60)
    print(f"Instagram:    @{data.get('username')}  ({data.get('account_type', 'unknown type')})")
    print("=" * 60)
    print("Add these as GitHub repository secrets")
    print("(repo > Settings > Secrets and variables > Actions > New repository secret):\n")
    print(f"IG_USER_ID\n{data['user_id']}\n")
    print("IG_ACCESS_TOKEN\n(the token you just pasted)\n")
    print("The token lasts 60 days. The 'Renew Instagram key' workflow renews it")
    print("automatically every week, as long as GH_SECRETS_TOKEN is set up (see README).")


if __name__ == "__main__":
    main()
