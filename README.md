# MCP Servers

## Hosted MCP Servers

I use the following services to host MCP servers:

- **[Metorial](https://metorial.com)** - Managed MCP server hosting
- **[Composio](https://composio.dev)** - MCP server platform with pre-built integrations

```bash
# Install dependencies
bun install
```

```bash
# Get API keys
bunx dotenv-vault@latest new <project-id>
bunx dotenv-vault@latest pull
```

```bash
# Install servers
bun run scripts/build-mcps.js
```

```bash
# Generate MCP configs
bun run scripts/generate-mcp-config.js
```

### Add MCPs to Claude Code (optional)
```bash
bun run scripts/add-mcps-to-claude-code.js
```