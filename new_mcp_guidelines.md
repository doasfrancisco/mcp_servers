# MCP Servers

How to build and configure MCP servers in this repo.

## What is an MCP server?

An MCP (Model Context Protocol) server exposes tools, resources, and prompts to AI clients like Claude Code, Claude Desktop, and Cursor. Each server lives in `mcps/` and provides a focused set of capabilities (Gmail, WhatsApp, Drive, etc.).

## Structure

```
mcps/
  my-server/
    server.py / mcp-server.js   # Required — the MCP server entry point
    README.md                   # Required — tools table, setup, usage
    requirements.txt / package.json
    icon_48x48.png              # Optional — icon for Claude Desktop
```

## Adding an icon for Claude Desktop

MCP servers can declare an icon that shows up in Claude Desktop's Connectors menu. The icon is served during the MCP initialization handshake via the `icons` field in `serverInfo`.

### Steps

#### 1. Create a 48x48 PNG

Resize your icon to 48x48 pixels and save it alongside your server code:

```python
from PIL import Image
img = Image.open("icon.png")
img = img.resize((48, 48), Image.LANCZOS)
img.save("icon_48x48.png")
```

#### 2. Add it to serverInfo

**TypeScript (MCP SDK):**

```js
import { readFileSync } from "node:fs";
import { join } from "node:path";

// For Electron apps, use app.getAppPath() instead of __dirname
const ICON_B64 = readFileSync(join(app.getAppPath(), "icon_48x48.png")).toString("base64");

const server = new McpServer({
  name: "my-server",
  version: "1.0.0",
  icons: [{
    src: `data:image/png;base64,${ICON_B64}`,
    mimeType: "image/png",
    sizes: ["48x48"],
  }],
});
```

**Python (FastMCP):**

```python
import base64
from pathlib import Path

icon_b64 = base64.b64encode(Path("icon_48x48.png").read_bytes()).decode()

# Pass icons in the server metadata (check FastMCP docs for exact API)
```

#### 3. For Electron apps: include in the build

Add the icon file to the `files` array in `package.json` so electron-builder bundles it:

```json
{
  "build": {
    "files": [
      "mcp-server.js",
      "icon_48x48.png"
    ]
  }
}
```

Use `app.getAppPath()` (not `__dirname`) to resolve the file path — `__dirname` points to a different location in packaged Electron apps.

### Icon spec (MCP 2025-11-25)

| Field | Required | Description |
|-------|----------|-------------|
| `src` | Yes | Data URI (`data:image/png;base64,...`) or HTTPS URL |
| `mimeType` | No | `image/png`, `image/jpeg`, `image/svg+xml`, `image/webp` |
| `sizes` | No | Array of size strings, e.g. `["48x48"]` |
| `theme` | No | `light` or `dark` |

Claude Desktop must support PNG and JPEG. SVG and WebP are optional.

## Connecting to Claude Desktop

Claude Desktop only supports **stdio** for local MCP servers. If your server runs over HTTP (like an Electron app), use a bridge:

### Direct stdio server

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcps/my-server", "fastmcp", "run", "server.py"]
    }
  }
}
```

### HTTP server via supergateway bridge

For servers that expose an HTTP endpoint (e.g. `http://localhost:PORT/mcp`), use [supergateway](https://github.com/supercorp-ai/supergateway) to bridge HTTP to stdio:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "supergateway", "--streamableHttp", "http://localhost:PORT/mcp"]
    }
  }
}
```

On macOS/Linux, drop the `"cmd", "/c"` prefix.

Config file location:
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

## Connecting to Claude Code

Claude Code supports HTTP MCP servers directly:

```bash
claude mcp add -s user my-server -- uv run --directory /path/to/mcps/my-server fastmcp run server.py
```

Or for HTTP servers:

```bash
claude mcp add --transport http my-server http://localhost:PORT/mcp
```
