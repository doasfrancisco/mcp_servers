# Gmail MCP Server

Full Gmail control with multi-account support via FastMCP.

## Setup

### 1. Google OAuth credentials (one-time)

Go to [Google Cloud Console](https://console.cloud.google.com):
1. Create a project → Enable **Gmail API**
2. Go to **Credentials** → Create **OAuth client ID** (Desktop app)
3. Download the JSON → save as `credentials/credentials.json`

> If configuring consent screen: choose External, add your email as test user, add Gmail API scope.

### 2. Add to Claude Code

```bash
claude mcp add -s user gmail -- uv run --directory /path/to/mcps/gmail fastmcp run server.py
```

Or for Claude Desktop, add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "gmail": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcps/gmail", "fastmcp", "run", "server.py"]
    }
  }
}
```

### 3. Use it

The first time you use a Gmail tool, a setup page opens in your browser. Add your Gmail accounts there — sign in with Google, pick an alias (personal, work, etc.), done.

## Tools

| Tool | Description |
|------|-------------|
| `gmail_search_messages` | Search with Gmail query syntax + date shorthands (`today`, `last_7d`, `last_30d`) |
| `gmail_read_message` | Read email by ID |
| `gmail_read_thread` | Read full thread |
| `gmail_list_drafts` | List drafts |
| `gmail_create_draft` | Create a draft (HTML formatting) |
| `gmail_send_message` | Send an email (HTML formatting) |
| `gmail_trash_messages` | Trash multiple emails across accounts in one call |
| `gmail_tag_messages` | Add/remove/swap tags per message in one call |
| `gmail_get_tagged` | Get emails by tag |
| `gmail_list_tags` | List all tags |
| `gmail_untrash_message` | Recover from trash |
| `gmail_list_trash` | List trashed emails |
| `gmail_unsubscribe` | Unsubscribe from mailing lists (RFC 8058 one-click) |
| `gmail_delete_tag` | Permanently delete a tag/label |
| `gmail_rename_tag` | Rename a tag (auto-applies ai/ prefix) |

## Multi-Account

- Omit `account` → queries all accounts
- Pass email or alias (e.g. `"personal"`, `"john@acmecorp.com"`)
- Write operations require `account`
