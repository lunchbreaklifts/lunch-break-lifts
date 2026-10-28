#!/usr/bin/env python3
"""
Renew the Instagram access token (it expires after 60 days; each renewal gives a
fresh 60 days). Run weekly by the "Renew Instagram key" GitHub workflow.

Prints ONLY the new token to stdout so the workflow can store it as a secret
without it appearing in logs. All messages go to stderr.
"""

import json
import os
import sys
from pathlib import Path

import requests

CONFIG = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
API = f"https://graph.instagram.com/{CONFIG.get('instagram_api_version', 'v23.0')}"


def main():
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        sys.exit("IG_ACCESS_TOKEN is not set.")

    r = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
        timeout=60,
    )
    data = r.json()
    if "error" in data or "access_token" not in data:
        err = data.get("error", data)
        msg = err.get("message", err) if isinstance(err, dict) else err
        sys.exit(f"Token renewal failed: {msg}\n"
                 "If the token already expired, generate a new one in the Meta app dashboard "
                 "and update the IG_ACCESS_TOKEN secret.")

    days = int(data.get("expires_in", 0)) // 86400
    print(f"Token renewed; valid for about {days} more days.", file=sys.stderr)
    print(data["access_token"])


if __name__ == "__main__":
    main()
