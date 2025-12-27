# MCP Servers

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