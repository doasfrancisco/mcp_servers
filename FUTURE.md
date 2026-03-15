## Future additions

### Automation

- **Save recurring Claude Code behaviors** — Track the most common tasks and workflows done from Claude Code (email triage, tag management, bulk operations, etc.). Save the behavior patterns so that in the future, OpenClaw can imitate and replay them autonomously without manual guidance.

### Signal skill

- **SessionStart hook for task context** — Add a global hook to `~/.claude/settings.json` that cats `~/.claude/signal/tasks.md` at session start, so every Claude Code session automatically knows what's in progress without needing `/signal`.

```json
{
  "type": "command",
  "command": "if [ -f ~/.claude/signal/tasks.md ]; then echo \"[Signal] Current tasks:\"; cat ~/.claude/signal/tasks.md; else echo \"[Signal] No tasks file found. Use /signal to set up tasks.\"; fi"
}
```

### Distribution

- **Compile MCP servers to native binaries** — Use `bun build --compile` (JS/TS) or Nuitka/PyInstaller (Python) to ship MCP servers as standalone executables. Prevents users from reading source code while keeping everything running locally. Claude Code itself does this — its CLI is a Bun-compiled binary.

### MCPs

- **Drive: upload files** — Add upload support to `drive_update_files` for pushing local files to Drive (binary uploads via `MediaFileUpload`). Currently `create` action only supports text content.
- **Drive: permissions management** — Add ability to share files/folders with specific users, change permissions, or make files public.
- **Share MCP usage guide** — Document how to use the Dámelo Share MCP for exporting, importing, and sharing sessions with teams.
- **Gmail: mailto unsubscribe** — Add mailto: support to `gmail_unsubscribe` (send an email to the unsubscribe address via Gmail API) for senders that don't support HTTP one-click.
- **Gmail: migrate existing auto/ labels to ai/** — Users with existing `auto/*` labels from before the prefix rename need a migration path. Could be a one-time script or a note in the README to use `gmail_rename_tag`.
- **Gmail: improve tool discoverability** — Claude guesses wrong param names when calling tools it hasn't discovered via `ToolSearch` first (e.g. `message_ids` instead of `messages`, `tag` as top-level instead of per-message). Improve docstrings to be more explicit about the schema, or explore ways to make the tool signatures self-evident so even undiscovered calls are less error-prone.
- **Gmail: send-as alias management** — Add `gmail.settings.sharing` scope and a `gmail_config` tool to manage send-as aliases from the MCP (list, add, remove). Requires re-auth of affected accounts after adding the scope.
- **Gmail: forward message** — Add `gmail_forward_message` tool. Forward an email to new recipients with proper `Fwd:` subject, quoted forwarded-message block (From/Date/Subject/To headers), HTML support, and threading headers. Currently users can't forward emails through the MCP at all. Inspired by GWS CLI's `+forward` command. See `docs/gmail-comparison-gws-cli.md`.
- **Gmail: download attachments** — Add `gmail_get_attachment` tool to download email attachments to local filesystem. We show attachment metadata but can't retrieve the actual files, blocking "save this PDF" workflows.
- **Gmail: reply-all recipient resolution** — Enhance `gmail_send_message` (or add dedicated mode) to auto-resolve all original To/CC recipients when replying, with deduplication and self-exclusion. Currently the AI has to manually extract recipients from the read result.

### Gmail: tool consolidation

Three tools are redundant with `gmail_search_messages`:

| Tool | Equivalent search query | Unique value? |
|---|---|---|
| `gmail_list_drafts` | `query="is:draft"` | Returns `draftId`, but no tool uses it (no update/send-draft) |
| `gmail_get_tagged` | `query="is:starred"` or `query="label:credentials"` | None — just tag→query resolution the AI can do itself |
| `gmail_list_trash` | `query="in:trash"` | None |

**Why not now:** These tools work fine and removing them requires updating the MCP instructions to teach the AI the equivalent Gmail queries. Low priority since the current tool count (15) isn't causing real confusion yet. Revisit if adding more tools pushes the count higher.

Two more potential merges:

| Merge | How | Worth it? |
|---|---|---|
| `gmail_create_draft` + `gmail_send_message` | Add `draft: bool = False` param | Saves 1 tool, but they're distinct write operations with different risk levels — drafts are safe, sends are irreversible. Merging could blur that boundary. |
| `gmail_read_message` + `gmail_read_thread` | Add `thread: bool = False` param | Saves 1 tool, but return shapes differ (single message vs list of messages). Merging makes the docstring harder to understand. |

**Why not now:** The borderline merges save 1 tool each but make the remaining tools harder to understand. The clarity tradeoff isn't worth it unless tool count becomes a real problem.
