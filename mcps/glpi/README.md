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

## Tools

| Tool | Description |
|------|-------------|
| `glpi_get_session` | Full session data: active profile, permissions, all profiles, entities, user info |
| `glpi_config` | Global GLPI configuration (curated by default, pass `full=true` for everything) |
| `glpi_get_item` | Get a single item by type and ID with optional related data |
| `glpi_get_items` | List items of any type (paginated) |
| `glpi_get_sub_items` | Get related sub-items (e.g. Ticket/5/TicketFollowup) |
| `glpi_list_search_options` | Discover searchable fields for any itemtype |
| `glpi_search` | Advanced search with criteria, sorting, and forced display columns |
| `glpi_tickets_today` | Quick shortcut: all tickets created today |

## Session Management

The server caches the GLPI session token to `.session.json` and reuses it across calls. On 401 (expired), it auto-refreshes using the permanent `user_token` from `.env`. No manual login needed.

## Background

### Why connect machines to GLPI?

1. **Asset tracking** — Know exactly what hardware the company owns, who has it, where it is, and its serial number. When someone leaves or a machine breaks, you know what exists and where it went.
2. **Linking assets to tickets** — When a user opens a support ticket ("my computer won't turn on"), the tech can link it to the specific Computer record for context: what model, what software is installed, has it had issues before.

### GLPI Agent

A small program installed on each machine (Windows, Linux, macOS, Android) that runs periodically and reports back to the GLPI server: CPU, RAM, disks, serial number, installed software, network interfaces, OS version, etc. Machines are registered automatically without manual data entry. Formerly known as FusionInventory Agent — GLPI 10 bundled it natively.

### Key config flags

- **`enabled_inventory`** — Whether the built-in inventory module is active. When on, GLPI accepts hardware/software reports from agents on the network.
- **`enable_api`** — Whether the REST API (`/apirest.php`) accepts requests. If off, none of the MCP tools work.
- **`maintenance_mode`** — When on, GLPI blocks normal users and shows a maintenance page. Only super-admins can log in.
