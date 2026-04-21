# Nia sources for mcp_servers

## Rules

- **Never pipe `nia` output through `head -N` or `tail -N`.** The output can be 2000+ lines. You MUST read ALL of it. If the output is split across chunks, read every chunk before proceeding. Missing a single source leads to wrong follow-up searches and wasted user time.
- **If the source is a package/library, always ask how to install it** (pip name, Python/Node version, any extras). E.g. `"how do I install X - pip name, python version, async extras?"`

## Sources

| Dep | Nia identifier | Type |
|---|---|---|
| `fastmcp` | `PrefectHQ/fastmcp` | repository |
| `google-api-python-client` / `google-auth` | `googleapis/google-api-python-client` | repository |
| `spotipy` | `spotipy-dev/spotipy` | repository |
| `beeper-desktop-api` | `beeper/desktop-api-python` | repository |
| `modelcontextprotocol` (MCP SDK) | `modelcontextprotocol/python-sdk` | repository |
| `whatsapp-web.js` | `pedroslopez/whatsapp-web.js` | repository |
| `electron` | `electron/electron` | repository |
| `express` | `expressjs/express` | repository |
| `glpi` | `glpi-project/glpi` | repository |
| `atlassian-python-api` (Jira/Confluence) | `atlassian-api/atlassian-python-api` | repository |

## Examples

```bash
nia search query "OAuth2 installed app flow" --repos googleapis/google-api-python-client
nia search query "how to authenticate with spotify web api" --repos spotipy-dev/spotipy
nia repos tree expressjs/express
nia repos read PrefectHQ/fastmcp src/fastmcp/server/app.py
nia repos grep pedroslopez/whatsapp-web.js "sendMessage"

nia sources resolve "https://platform.claude.com/docs" --type documentation
nia sources tree <UUID>
nia sources read <UUID> build-with-claude/prompt-caching.md
nia sources grep <UUID> "cache_control"
```

### Multi-source query

```bash
# Example
nia search query "stdio transport for MCP servers" \
  --repos PrefectHQ/fastmcp,modelcontextprotocol/python-sdk \
  --docs "https://platform.claude.com/docs"
```