# Nia MCP Server

Knowledge agent for indexing and searching repositories and documentation.

## Installation

### 1. Install via pipx

```bash
pipx install nia-mcp-server
```

### 2. Add to Claude Code

```bash
claude mcp add nia -e NIA_API_KEY=YOUR_API_KEY -e NIA_API_URL=https://apigcp.trynia.ai/ --scope user -- pipx run nia-mcp-server
```

### 3. Restart your terminal

After installation, you must close and reopen your terminal completely for pipx to be in your PATH and for Nia to get picked up by Claude Code. Close every terminal manually.
