# GLPI MCP Server

IT service management via GLPI REST API with FastMCP. Session tokens are cached and auto-refreshed.

## Setup

1. **GLPI API access** — Enable the API in GLPI (Configuracion > General > API), create an API client, generate a user token from Preferencias > Claves de acceso remoto
2. **Environment** — Add to the repo root `.env`:
   ```
   GLPI_API_URL='https://your-host/apirest.php'
   GLPI_APP_TOKEN='your_app_token'
   GLPI_USER_TOKEN='your_user_token'
   ```
3. **Install** — `uv sync` inside `mcps/glpi/`
4. **Add to Claude Code:**
   ```bash
   claude mcp add -s user glpi -- uv run --directory /path/to/glpi fastmcp run server.py
   ```

## Session Management

The server caches the GLPI session token to `.session.json` and reuses it across calls. On 401 (expired), it auto-refreshes using the permanent `user_token` from `.env`. No manual login needed.


### Key config flags

- **`enable_api`** — Whether the REST API accepts requests. If off, none of the MCP tools work.
- **`maintenance_mode`** — When on, GLPI blocks normal users.
