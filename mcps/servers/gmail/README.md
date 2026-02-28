# Gmail MCP Server

Full Gmail control with multi-account support via FastMCP.

## Setup

1. **Google Cloud Console** — Enable Gmail API, create OAuth 2.0 Desktop credentials, save as `credentials/credentials.json`
2. **Accounts** — `cp accounts.json.example accounts.json` and fill in your emails
3. **Authenticate** — `uv run python setup_auth.py` (opens browser per account)
4. **Add to Claude Code:**
   ```bash
   claude mcp add -s user gmail -- uv run --directory /path/to/gmail fastmcp run server.py
   ```

## Tools

| Tool | Description |
|------|-------------|
| `gmail_get_profile` | Account profile info |
| `gmail_search_messages` | Search with Gmail query syntax + date shorthands (`today`, `last_7d`, `last_30d`) |
| `gmail_read_message` | Read email by ID |
| `gmail_read_thread` | Read full thread |
| `gmail_list_drafts` | List drafts |
| `gmail_create_draft` | Create a draft |
| `gmail_send_message` | Send an email |
| `gmail_trash_message` | Trash one email |
| `gmail_trash_messages` | Trash multiple emails across accounts in one call |
| `gmail_tag_messages` | Add/remove/swap tags per message in one call |
| `gmail_get_tagged` | Get emails by tag |
| `gmail_list_tags` | List all tags |
| `gmail_untrash_message` | Recover from trash |
| `gmail_list_trash` | List trashed emails |

## Multi-Account

- Omit `account` → queries all accounts
- Pass email or alias (e.g. `"personal"`, `"john@acmecorp.com"`)
- Write operations require `account`
