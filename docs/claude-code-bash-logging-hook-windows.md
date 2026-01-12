# Claude Code Bash Logging Hook (Windows)

Logs all Bash commands Claude Code runs to a file.

## Setup

Add this to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "jq -r \"[.tool_input.command, (.tool_input.description // \\\"No description\\\")] | join(\\\" - \\\")\" >> %USERPROFILE%\\.claude\\bash-command-log.txt"
          }
        ]
      }
    ]
  }
}
```

**Requires:** `jq` installed (`winget install jqlang.jq`)

**Log location:** `%USERPROFILE%\.claude\bash-command-log.txt`

## Why Windows Needs Different Syntax

The official docs provide a Unix command that fails on Windows:

```bash
jq -r '"\(.tool_input.command) - \(.tool_input.description // "No description")"' >> ~/.claude/bash-command-log.txt
```

| Unix | Windows |
|------|---------|
| Single quotes `'...'` | Use double quotes (escaped in JSON) |
| `~` | `%USERPROFILE%` |
| `\(...)` interpolation | Use `[...] \| join()` to avoid nested quotes |
