"""Web-based setup for Gmail MCP Server.

Starts a local HTTP server that guides users through adding Gmail accounts
via Google OAuth. No manual JSON editing required.

Can run standalone (`uv run python setup_server.py`) or be started
automatically by the MCP server on first run.
"""

import json
import socket
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

GMAIL_DIR = Path(__file__).parent
CREDENTIALS_PATH = GMAIL_DIR / "credentials" / "credentials.json"
ACCOUNTS_PATH = GMAIL_DIR / "accounts.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# ── State ──────────────────────────────────────────────────────────────
_port: int = 0
_accounts: list[dict] = []          # [{email, alias}]
_pending_creds: dict[str, Credentials] = {}  # email → creds waiting for alias
_pending_flow: Flow | None = None   # OAuth flow in progress (carries PKCE verifier)
_setup_complete = threading.Event()


def _find_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _redirect_uri() -> str:
    return f"http://localhost:{_port}/callback"


# ── HTML ───────────────────────────────────────────────────────────────

def _page(title: str, body: str) -> bytes:
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 480px;
         margin: 60px auto; padding: 0 20px; color: #1a1a1a; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 8px; }}
  p.sub {{ color: #666; margin-bottom: 32px; }}
  .btn {{ display: inline-block; padding: 12px 24px; border-radius: 8px;
          text-decoration: none; font-weight: 600; cursor: pointer;
          border: none; font-size: 1rem; }}
  .btn-primary {{ background: #4285f4; color: white; }}
  .btn-primary:hover {{ background: #3367d6; }}
  .btn-finish {{ background: #1a1a1a; color: white; }}
  .btn-finish:hover {{ background: #333; }}
  .btn-alias {{ background: #f0f0f0; color: #1a1a1a; margin: 4px; }}
  .btn-alias:hover {{ background: #e0e0e0; }}
  .account {{ padding: 12px 16px; background: #f8f8f8; border-radius: 8px;
              margin-bottom: 8px; display: flex; justify-content: space-between; }}
  .account .email {{ font-weight: 500; }}
  .account .alias {{ color: #666; }}
  input[type=text] {{ padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;
                      font-size: 1rem; width: 200px; }}
  .actions {{ margin-top: 24px; display: flex; gap: 12px; align-items: center; }}
  .section {{ margin-bottom: 32px; }}
  select {{ padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;
            font-size: 1rem; background: white; }}
  .config {{ background: #f0f0f0; padding: 16px; border-radius: 8px;
             font-family: monospace; font-size: 0.85rem; white-space: pre-wrap;
             word-break: break-all; margin-bottom: 16px; }}
  label {{ display: flex; align-items: center; gap: 8px; padding: 8px 0; cursor: pointer; }}
</style>
</head><body>{body}</body></html>""".encode()


def _main_page() -> bytes:
    accounts_html = ""
    for acc in _accounts:
        accounts_html += (
            f'<div class="account">'
            f'<span class="email">{acc["email"]}</span>'
            f'<span class="alias">{acc["alias"]}</span>'
            f'</div>'
        )

    if _accounts:
        accounts_section = f'<div class="section">{accounts_html}</div>'
        finish_btn = '<a href="/finish" class="btn btn-finish">Finish setup</a>'
    else:
        accounts_section = ""
        finish_btn = ""

    return _page("Gmail MCP Setup", f"""
        <h1>Gmail MCP Setup</h1>
        <p class="sub">Add your Gmail accounts to get started.</p>
        {accounts_section}
        <div class="actions">
            <a href="/add" class="btn btn-primary">Add Gmail account</a>
            {finish_btn}
        </div>
    """)


def _alias_page(email: str) -> bytes:
    defaults = ["personal", "work", "university"]
    # Remove aliases already taken
    taken = {a["alias"] for a in _accounts}
    buttons = "".join(
        f'<a href="/save?email={email}&alias={a}" class="btn btn-alias">{a}</a>'
        for a in defaults if a not in taken
    )
    return _page("Pick an alias", f"""
        <h1>Account added</h1>
        <p class="sub">Signed in as <strong>{email}</strong></p>
        <div class="section">
            <p style="margin-bottom: 12px;">Pick a name for this account:</p>
            {buttons}
        </div>
        <form action="/save" method="get" style="display: flex; gap: 8px; align-items: center;">
            <input type="hidden" name="email" value="{email}">
            <input type="text" name="alias" placeholder="custom alias">
            <button type="submit" class="btn btn-alias">Save</button>
        </form>
    """)


def _finish_page() -> bytes:
    if len(_accounts) == 1:
        # Skip picker, auto-select the only account
        return _done_page(_accounts[0]["alias"])

    options = "".join(
        f'<label><input type="radio" name="default" value="{a["alias"]}"'
        f'{" checked" if i == 0 else ""}> '
        f'{a["alias"]} ({a["email"]})</label>'
        for i, a in enumerate(_accounts)
    )
    return _page("Pick default account", f"""
        <h1>Almost done</h1>
        <p class="sub">Which account should be the default?</p>
        <form action="/done" method="get">
            <div class="section">{options}</div>
            <button type="submit" class="btn btn-finish">Finish</button>
        </form>
    """)


def _done_page(default_alias: str) -> bytes:
    gmail_dir = str(GMAIL_DIR).replace("\\", "/")
    claude_code_cmd = f'claude mcp add -s user gmail -- uv run --directory "{gmail_dir}" fastmcp run server.py'
    desktop_config = json.dumps({
        "mcpServers": {
            "gmail": {
                "command": "uv",
                "args": ["run", "--directory", gmail_dir, "fastmcp", "run", "server.py"],
            }
        }
    }, indent=2)

    accounts_list = "".join(
        f'<div class="account">'
        f'<span class="email">{a["email"]}</span>'
        f'<span class="alias">{a["alias"]}{"  (default)" if a["alias"] == default_alias else ""}</span>'
        f'</div>'
        for a in _accounts
    )

    return _page("Setup complete", f"""
        <h1>Setup complete</h1>
        <p class="sub">{len(_accounts)} account(s) ready.</p>
        <div class="section">{accounts_list}</div>
        <div class="section">
            <p style="margin-bottom: 8px; font-weight: 600;">Claude Code</p>
            <div class="config">{claude_code_cmd}</div>
        </div>
        <div class="section">
            <p style="margin-bottom: 8px; font-weight: 600;">Claude Desktop — add to config</p>
            <div class="config">{desktop_config}</div>
        </div>
        <p style="color: #666;">You can close this page.</p>
    """)


# ── Handler ────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/":
            self._respond(200, _main_page())

        elif path == "/add":
            global _pending_flow
            if not CREDENTIALS_PATH.exists():
                self._respond(500, _page("Error",
                    "<h1>Missing credentials.json</h1>"
                    f"<p>Download OAuth credentials from Google Cloud Console and save to:</p>"
                    f'<div class="config">{CREDENTIALS_PATH}</div>'
                ))
                return
            _pending_flow = Flow.from_client_secrets_file(
                str(CREDENTIALS_PATH), scopes=SCOPES, redirect_uri=_redirect_uri(),
            )
            url, _ = _pending_flow.authorization_url(access_type="offline", prompt="consent")
            self._redirect(url)

        elif path == "/callback":
            code = params.get("code", [None])[0]
            if not code or not _pending_flow:
                self._redirect("/")
                return
            try:
                _pending_flow.fetch_token(code=code)
                creds = _pending_flow.credentials
                service = build("gmail", "v1", credentials=creds)
                profile = service.users().getProfile(userId="me").execute()
                email = profile["emailAddress"]
                _pending_creds[email] = creds
                self._respond(200, _alias_page(email))
            except Exception as e:
                self._respond(500, _page("Error", f"<h1>Authentication failed</h1><p>{e}</p>"))

        elif path == "/save":
            email = params.get("email", [None])[0]
            alias = params.get("alias", [None])[0]
            if email and alias and email in _pending_creds:
                alias = alias.strip().lower().replace(" ", "_")
                creds = _pending_creds.pop(email)
                # Save token
                token_path = GMAIL_DIR / "credentials" / f"token_{alias}.json"
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(creds.to_json())
                _accounts.append({"email": email, "alias": alias})
            self._redirect("/")

        elif path == "/finish":
            if len(_accounts) == 1:
                _save_config(_accounts[0]["alias"])
            self._respond(200, _finish_page())
            if len(_accounts) == 1:
                threading.Timer(0.5, _setup_complete.set).start()

        elif path == "/done":
            default = params.get("default", [_accounts[0]["alias"] if _accounts else ""])[0]
            _save_config(default)
            self._respond(200, _done_page(default))
            # Signal completion after response is sent
            threading.Timer(0.5, _setup_complete.set).start()

        else:
            self._respond(404, _page("Not found", "<h1>Not found</h1>"))

    def _respond(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, url: str):
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress request logs


# ── Config persistence ─────────────────────────────────────────────────

def _save_config(default_alias: str):
    config = {
        "accounts": [{"email": a["email"], "alias": a["alias"]} for a in _accounts],
        "default": default_alias,
    }
    ACCOUNTS_PATH.write_text(json.dumps(config, indent=2))


# ── Public API ─────────────────────────────────────────────────────────

def start_setup_server() -> int:
    """Start the setup server in a background thread. Returns the port."""
    global _port
    _port = _find_port()
    server = HTTPServer(("127.0.0.1", _port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return _port


def is_setup_complete() -> bool:
    return _setup_complete.is_set()


def wait_for_setup(timeout: float | None = None) -> bool:
    return _setup_complete.wait(timeout=timeout)


def needs_setup() -> bool:
    """Check if setup is needed (no accounts.json or no valid tokens)."""
    if not ACCOUNTS_PATH.exists():
        return True
    try:
        config = json.loads(ACCOUNTS_PATH.read_text())
        return not config.get("accounts")
    except Exception:
        return True


# ── Standalone entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    if not needs_setup():
        print("Gmail MCP is already configured.")
        config = json.loads(ACCOUNTS_PATH.read_text())
        for acc in config["accounts"]:
            print(f"  {acc['alias']}: {acc['email']}")
        answer = input("\nRe-run setup? (y/N): ").strip().lower()
        if answer != "y":
            raise SystemExit(0)
        # Reset state for re-setup
        _accounts.clear()

    port = start_setup_server()
    url = f"http://localhost:{port}"
    print(f"Opening setup at {url}")
    webbrowser.open(url)
    wait_for_setup()
    print("Setup complete!")
