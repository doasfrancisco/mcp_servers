# Claude Code Skill Hooks

Add hooks to skill frontmatter to run commands during the skill lifecycle.

## Setup

Edit `SKILL.md` in your skill folder (`~/.claude/skills/your-skill/SKILL.md`):

```yaml
---
name: your-skill
description: "Your skill description"
hooks:
  Stop:
    - hooks:
        - type: command
          command: "echo %DATE% %TIME% - your-skill completed >> %USERPROFILE%\\.claude\\skill-usage.txt"
---
```

## Hook Events

| Event | When it runs |
|-------|--------------|
| `PreToolUse` | Before a tool is called |
| `PostToolUse` | After a tool completes |
| `Stop` | When the skill finishes |

## Options

| Option | Description |
|--------|-------------|
| `matcher` | Regex to match tools (`"Bash"`, `"Edit\|Write"`, `"*"` for all) |
| `once` | `true` = run only once, not every match |

## Skill Hooks vs settings.json Hooks

| | settings.json | Skill Frontmatter |
|-|---------------|-------------------|
| Scope | Global | Only while skill is active |
| Cleanup | Manual | Automatic |
| `once` | No | Yes |
