# MCP Servers

## Hosted MCP Servers

I use the following services to host MCP servers:

- **[Metorial](https://metorial.com)** - Managed MCP server hosting

```bash
# Install dependencies
bun install
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

### How to get your API keys
```bash
bunx dotenv-vault@latest new <project-id>
bunx dotenv-vault@latest pull
```