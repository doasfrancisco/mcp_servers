---
name: claude-setup
description: Set up a Claude Code project environment — sound themes, file picker, and global hooks. Use when the user asks to set up sounds, install a sound theme, set up the file picker, or configure their Claude Code environment.
---

# Claude Setup

Set up a Claude Code project environment. Ask the user which features to install:

1. **Sound theme** — install notification sounds into `.claude/sounds/`
2. **File picker** — install the `file-suggestion.sh` script into `.claude/`
3. **CLAUDE.md** — generate a project CLAUDE.md
4. **Global hooks** — generate `~/.claude/settings.json` with sound hooks and copy `play-sound.py` to `~/.claude/`

## 1. Sound Theme

Ask the user which theme they want. List available themes:

```bash
ls <skill-path>/assets/sounds/ | grep -v '\.'
```

Install with:

```bash
bash <skill-path>/scripts/install_sounds.sh <skill-path>/assets <theme-name>
```

This creates `.claude/sounds/` and converts all audio files to `.wav` via ffmpeg.

## 2. File Picker

Copy the file suggestion script:

```bash
mkdir -p .claude
cp <skill-path>/assets/file-suggestion.sh .claude/
```

Then add to the project's `.claude/settings.json`:

```json
{
  "fileSuggestion": {
    "type": "command",
    "command": "bash .claude/file-suggestion.sh"
  }
}
```

## 3. CLAUDE.md

Generate a `CLAUDE.md` at the project root.

Always include a **Commits** section:

```markdown
## Commits

Use conventional commits. No co-authoring.

Every message MUST answer both **what** changed and **why** it changed.

- `feat:` for new functionality
- `fix:` for bug fixes
- `chore:` for everything else

Bad: `feat: add repo mapping` — missing the why.
Good: `feat: add repo mapping to centralize project navigation`

Always stage with `git add .` before committing.

Bad: `git add file1.txt file2.txt && git commit -m "..."`
Good: `git add . && git commit -m "..."`
```

Ask if this is a **meta-repo** (multiple independent git repos in subfolders). If yes, also include:

```markdown
## Repositories

| Folder | Role | Notes |
|---|---|---|
| `folder/` | What it does | Extra context |

## Conventions

- All subdirectories are gitignored — each is tracked in its own repo.
- This repo holds only top-level documentation and mapping.
```

Populate the Repositories table by scanning top-level directories and asking the user to describe each.

For meta-repos, also generate a `.gitignore` listing every folder from the Repositories table (one `folder/` per line).

## 4. Global Hooks

Copy the sound player script:

```bash
cp <skill-path>/scripts/play-sound.py ~/.claude/play-sound.py
```

The global `~/.claude/settings.json` hooks should reference the skill's default fallback sounds (the Peon `.wav` files in `assets/sounds/`). Generate hooks for these events:

- **SessionStart** → `start.wav`
- **UserPromptSubmit** → `submit.wav`
- **Notification** → `notify.wav`
- **Stop** → `done.wav`

Each hook command:

```
python ~/.claude/play-sound.py <sound_name>.wav <skill-path>/assets/sounds/<sound_name>.wav
```
