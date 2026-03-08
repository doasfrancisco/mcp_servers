"""GLPI API connection test.

Tests authentication and basic endpoint access against
ti.pulsosalud.com/apirest.php
"""

import os
import sys
from datetime import date

import urllib3
import requests
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load .env from repo root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE_URL = os.getenv("GLPI_API_URL", "https://ti.pulsosalud.com/apirest.php")
APP_TOKEN = os.getenv("GLPI_APP_TOKEN")
USER_TOKEN = os.getenv("GLPI_USER_TOKEN")
SUPER_ADMIN_PROFILE_ID = 4


def _headers(session_token: str) -> dict:
    return {"Session-Token": session_token, "App-Token": APP_TOKEN}


def _get(url: str, session_token: str, **kwargs):
    return requests.get(url, headers=_headers(session_token), timeout=15, verify=False, **kwargs)


def init_session() -> str:
    resp = requests.get(
        f"{BASE_URL}/initSession",
        headers={"Authorization": f"user_token {USER_TOKEN}", "App-Token": APP_TOKEN},
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    token = resp.json()["session_token"]
    print(f"[OK] Session initialized: {token[:12]}...")
    return token


# def switch_to_super_admin(session_token: str):
#     resp = requests.post(
#         f"{BASE_URL}/changeActiveProfile",
#         headers={**_headers(session_token), "Content-Type": "application/json"},
#         json={"profiles_id": SUPER_ADMIN_PROFILE_ID},
#         timeout=15,
#         verify=False,
#     )
#     if resp.ok:
#         print("[OK] Switched to Super-Admin profile")
#     else:
#         print(f"[FAIL] Profile switch: {resp.status_code} — {resp.text[:120]}")


def test_endpoints(session_token: str):
    endpoints = [
        # ITIL
        ("Ticket", "/Ticket?range=0-4"),
        ("Problem", "/Problem?range=0-4"),
        ("Change", "/Change?range=0-4"),
        # Assets
        ("Computer", "/Computer?range=0-4"),
        ("Monitor", "/Monitor?range=0-4"),
        ("NetworkEquipment", "/NetworkEquipment?range=0-4"),
        ("Printer", "/Printer?range=0-4"),
        ("Phone", "/Phone?range=0-4"),
        ("Peripheral", "/Peripheral?range=0-4"),
        ("Software", "/Software?range=0-4"),
        # Management
        ("User", "/User?range=0-4"),
        ("Group", "/Group?range=0-4"),
        ("Entity", "/Entity?range=0-4"),
        ("Location", "/Location?range=0-4"),
        ("Supplier", "/Supplier?range=0-4"),
        ("Contract", "/Contract?range=0-4"),
        ("Contact", "/Contact?range=0-4"),
        ("Document", "/Document?range=0-4"),
        ("Budget", "/Budget?range=0-4"),
        # Config
        ("ITILCategory", "/ITILCategory?range=0-4"),
        ("Profile", "/Profile?range=0-4"),
        ("State", "/State?range=0-4"),
    ]

    ok, fail = [], []
    for name, path in endpoints:
        resp = _get(f"{BASE_URL}{path}", session_token)
        if resp.ok:
            items = resp.json()
            count = len(items) if isinstance(items, list) else "?"
            ok.append((name, count))
        else:
            fail.append((name, resp.status_code))

    print(f"\n--- Endpoint access: {len(ok)} OK, {len(fail)} FAIL ---\n")
    for name, count in ok:
        print(f"  [OK]   {name:<20} {count} items")
    for name, code in fail:
        print(f"  [FAIL] {name:<20} HTTP {code}")


def todays_tickets(session_token: str):
    today = date.today().isoformat()
    params = {
        "criteria[0][field]": 15,
        "criteria[0][searchtype]": "morethan",
        "criteria[0][value]": f"{today} 00:00:00",
        "forcedisplay[0]": 1,
        "forcedisplay[1]": 2,
        "forcedisplay[2]": 12,
        "forcedisplay[3]": 15,
        "forcedisplay[4]": 7,
        "range": "0-50",
    }
    resp = _get(f"{BASE_URL}/search/Ticket", session_token, params=params)
    if not resp.ok:
        print(f"[FAIL] Today's tickets: {resp.status_code} — {resp.text[:120]}")
        return

    data = resp.json()
    total = data.get("totalcount", 0)
    print(f"\n--- Tickets today ({today}): {total} ---\n")

    for item in data.get("data", []):
        tid = item.get("2", "?")
        name = item.get("1", "?")
        status = item.get("12", "?")
        created = item.get("15", "?")
        category = item.get("7", "—")
        print(f"  #{tid} [{status}] {name}")
        print(f"       Created: {created} | Category: {category}")


def kill_session(session_token: str):
    resp = requests.get(
        f"{BASE_URL}/killSession",
        headers=_headers(session_token),
        timeout=10,
        verify=False,
    )
    if resp.ok:
        print("\n[OK] Session closed")


def main():
    if not APP_TOKEN or not USER_TOKEN:
        print("Missing GLPI_APP_TOKEN and/or GLPI_USER_TOKEN in .env")
        sys.exit(1)

    print(f"API: {BASE_URL}\n")
    session_token = init_session()
    # switch_to_super_admin(session_token)
    test_endpoints(session_token)
    todays_tickets(session_token)
    kill_session(session_token)
    print("All done.")


if __name__ == "__main__":
    main()
