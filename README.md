# MCP Servers

```bash
# 1. Install servers
node setup.js
```

```bash
# 2. Add API keys
cp .env.example .env
# Edit .env with your keys
```

```bash
# 3. Generate MCP configs
node generate-config.js
```

```bash
# 4. Add to Claude Code (optional)
node add-mcps-to-claude-code.js
```