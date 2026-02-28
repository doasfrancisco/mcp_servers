"""CLI script to authenticate Gmail accounts via OAuth2.

Run this once per account to generate token files:
    python setup_auth.py
"""

import json
import sys
from pathlib import Path

from auth import load_credentials, run_oauth_flow


def main():
    config_path = Path(__file__).parent / "accounts.json"
    if not config_path.exists():
        print("Error: accounts.json not found.")
        print("Copy accounts.json.example to accounts.json and configure your accounts.")
        sys.exit(1)

    config = json.loads(config_path.read_text())
    accounts = config.get("accounts", [])

    if not accounts:
        print("Error: No accounts configured in accounts.json.")
        sys.exit(1)

    print(f"Found {len(accounts)} account(s) to authenticate.\n")

    for acc in accounts:
        alias = acc["alias"]
        email = acc["email"]

        existing = load_credentials(alias)
        if existing and not existing.expired:
            print(f"  [{alias}] {email} — already authenticated (valid token)")
            continue

        print(f"  [{alias}] {email} — starting OAuth flow...")
        print(f"         A browser window will open. Sign in with: {email}")
        try:
            run_oauth_flow(alias)
            print(f"  [{alias}] Authenticated successfully!\n")
        except Exception as e:
            print(f"  [{alias}] Authentication failed: {e}\n")

    print("Done! You can now use the Gmail MCP server.")


if __name__ == "__main__":
    main()
