# Google Drive MCP Server

Multi-account Google Drive access via FastMCP.

## Setup

### 1. Google OAuth credentials (one-time)

Go to [Google Cloud Console](https://console.cloud.google.com):
1. Create a project (or reuse an existing one) → Enable **Google Drive API**
2. Go to **Credentials** → Create **OAuth client ID** (Desktop app)
3. Download the JSON → save as `credentials/credentials.json`

> If configuring consent screen: choose External, add your email as test user, add Drive API scope.

### 2. Add to Claude Code

```bash
claude mcp add -s user drive -- uv run --directory /path/to/mcps/drive fastmcp run server.py
```

Or for Claude Desktop, add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "drive": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcps/drive", "fastmcp", "run", "server.py"]
    }
  }
}
```

### 3. Use it

The first time you use a Drive tool, a setup page opens in your browser. Add your Google accounts there — sign in with Google, pick an alias (personal, work, etc.), done.

## Tools

| Tool | Description |
|------|-------------|
| `drive_list_files` | List files/folders in a Drive folder (recursive by default, merges all accounts) |
| `drive_read_file` | Read file content — Docs→text, Sheets→CSV, binary→metadata only. Auto-picks best account |
| `drive_search_files` | Search by file name or full text across all accounts |
| `drive_update_files` | Move, delete (trash), or create files. Requires explicit account |
| `drive_create_folder` | Create a new folder. Requires explicit account |

## Multi-Account

- **Read-only tools** (list, read, search) automatically try all accounts — no `account` parameter needed
- **Write tools** (update, create folder) require an explicit `account` (email or alias)
- Read auto-picks the account with highest permission (owner > editor > viewer)
- List/search merge results across accounts, deduplicating by file ID
