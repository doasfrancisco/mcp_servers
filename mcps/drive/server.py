"""Google Drive MCP Server — multi-account Drive access."""

import json
import webbrowser
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from drive_client import DriveClient, extract_file_id
from setup_server import is_setup_complete, needs_setup, start_setup_server


# ── Auto-setup on first run ───────────────────────────────────────────

_setup_port: int | None = None


@asynccontextmanager
async def _lifespan(server):
    global _setup_port
    if needs_setup():
        _setup_port = start_setup_server()
        webbrowser.open(f"http://localhost:{_setup_port}")
    yield


mcp = FastMCP(
    "Google Drive",
    lifespan=_lifespan,
    instructions="""IMPORTANT: Always discover a tool's schema with ToolSearch BEFORE calling it for the first time.

Before executing any write operation (move, delete, create file, create folder), always tell the user exactly what you're about to do and STOP your turn. Do NOT call the tool in the same message. Wait for the user to reply with confirmation before making the call.

When presenting file results to the user, always:
- Show EVERY file — never truncate, summarize, or skip results
- Group by account (personal, work, university)
- Number each file sequentially within its account group (1., 2., 3.)
- Show the count per account
- Format: **file name** — type, size (e.g. **Invoice_2024.pdf** — PDF, 2.4 MB)
- Folders get a trailing / (e.g. **Documents/**)
- Show total count and total size at the end

When presenting file content (drive_read_file):
- Show the full file content — never truncate or summarize
- For CSV (Google Sheets), show the raw CSV data

When moving, deleting, or creating files (drive_update_files):
- action "move": moves files to a destination folder (server-side, no download)
- action "delete": trashes files (recoverable from Google Drive trash)
- action "create": creates new files with optional text content

You can pass either a Google Drive URL or a raw file/folder ID to any tool that accepts IDs.

Read-only tools (list, read, search) automatically try all configured accounts — no account parameter needed.
Write tools (update, create folder) require an explicit account parameter.
""",
)

_client: DriveClient | None = None


def _get_client() -> DriveClient:
    """Get the Drive client, or raise a setup message if not configured."""
    global _client
    if needs_setup():
        if _setup_port and not is_setup_complete():
            raise RuntimeError(
                f"Drive setup in progress. Complete the setup in your browser "
                f"(http://localhost:{_setup_port}), then try again."
            )
        if needs_setup():
            port = start_setup_server()
            webbrowser.open(f"http://localhost:{port}")
            raise RuntimeError(
                f"Drive is not configured. A setup page opened in your browser "
                f"(http://localhost:{port}). Add your Google accounts there, then try again."
            )
    if _client is None:
        _client = DriveClient()
    return _client


def _json(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


# ── Tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def drive_list_files(
    folder: str,
    recursive: bool = True,
) -> str:
    """List files and folders inside a Google Drive folder. Show all results to the user — never truncate or summarize.

    Tries all configured accounts and merges results (deduplicates by file ID).
    Accepts any Google Drive URL or raw folder ID.

    Each result includes: name, type (file/folder), mimeType, size, path, and which account found it.

    Args:
        folder: Google Drive folder URL or folder ID.
            Examples: "https://drive.google.com/drive/folders/abc123", "abc123"
        recursive: If true (default), includes all subfolders. Set false for immediate children only.
    """
    folder_id = extract_file_id(folder)
    return _json(_get_client().list_files(folder_id, recursive))


@mcp.tool()
def drive_read_file(file: str) -> str:
    """Read the content of a file from Google Drive. Show the full content to the user — never truncate or summarize.

    Auto-picks the account with highest permission (owner > editor > viewer).
    Accepts any Google Drive URL or raw file ID.

    Export behavior:
    - Google Docs / Slides → plain text
    - Google Sheets → CSV (raw data)
    - Text files (< 5MB) → raw content
    - Binary files (images, PDFs, etc.) → metadata only (name, size, mimeType, webViewLink)

    Args:
        file: Google Drive file URL or file ID.
            Examples: "https://drive.google.com/file/d/abc123/view", "https://docs.google.com/document/d/abc123/edit", "abc123"
    """
    file_id = extract_file_id(file)
    return _json(_get_client().read_file(file_id))


@mcp.tool()
def drive_update_files(
    files: list[str],
    action: str,
    account: str,
    destination: str | None = None,
    content: str | None = None,
    mime_type: str = "text/plain",
) -> str:
    """STOP: Tell the user what you're about to do and wait for confirmation. Do NOT call this tool in the same turn as the user's request.

    Perform write operations on Drive files. Account is always required.

    Actions:
    - "move": moves files to a destination folder (server-side, no download/upload). Requires destination.
    - "delete": trashes files (recoverable from Google Drive trash for 30 days).
    - "create": creates new files. files= is a list of file names to create.

    Examples:
    - Move 2 files: files=["id1", "id2"], action="move", destination="folder_id", account="personal"
    - Delete: files=["id1"], action="delete", account="work"
    - Create: files=["notes.txt"], action="create", destination="folder_id", content="hello", account="personal"

    Args:
        files: List of file URLs or IDs. For "create", this is a list of file names to create.
        action: One of "move", "delete", or "create".
        account: Email or alias — required for all write operations.
        destination: For "move": destination folder URL/ID. For "create": parent folder URL/ID.
        content: For "create": text content of the new file.
        mime_type: For "create": MIME type (default "text/plain").
    """
    client = _get_client()

    if action == "move":
        if not destination:
            return _json({"error": "destination is required for move action"})
        file_ids = [extract_file_id(f) for f in files]
        dest_id = extract_file_id(destination)
        return _json(client.move_files(file_ids, dest_id, account))

    elif action == "delete":
        file_ids = [extract_file_id(f) for f in files]
        return _json(client.delete_files(file_ids, account))

    elif action == "create":
        results = []
        parent_id = extract_file_id(destination) if destination else None
        for name in files:
            result = client.create_file(name, account, parent_id, content, mime_type)
            results.append(result)
        return _json(results)

    else:
        return _json({"error": f"Unknown action '{action}'. Use: move, delete, create"})


@mcp.tool()
def drive_search_files(
    name: str | None = None,
    query: str | None = None,
    max_results: int = 50,
) -> str:
    """Search for files in Google Drive. Searches all accounts and merges results. Show all results to the user — never truncate.

    Two search modes (can combine both):
    - name: matches file names (partial, case-insensitive) — e.g. name="invoice" finds "Invoice_2024.pdf"
    - query: full text search inside file contents (like Drive's search bar)

    Each result includes: name, type, mimeType, size, modifiedTime, and which account found it.

    Args:
        name: Search by file name (partial match, case-insensitive).
        query: Full text search across file contents (like Drive's search bar).
        max_results: Maximum number of results (default 50).
    """
    if not name and not query:
        return _json({"error": "Provide at least one of: name, query"})
    return _json(_get_client().search_files(name, query, max_results))


@mcp.tool()
def drive_create_folder(
    name: str,
    account: str,
    parent: str | None = None,
) -> str:
    """STOP: Tell the user what folder you're about to create and wait for confirmation. Do NOT call this tool in the same turn as the user's request.

    Create a new folder in Google Drive. Returns the new folder's ID, name, and webViewLink.

    Args:
        name: Name for the new folder.
        account: Email or alias — required for write operations.
        parent: Parent folder URL or ID. Omit to create in Drive root.
    """
    parent_id = extract_file_id(parent) if parent else None
    return _json(_get_client().create_folder(name, account, parent_id))
