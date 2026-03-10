---
name: signal
description: Task intake, orchestration, and context tracking. Use when the user shows a photo of handwritten tasks, says "work", "let's go", "what's next", "read my tasks", "status", "check tasks", or invokes /signal. Syncs task state from session logs, manages daily task files, dispatches work to terminal tabs, and persists context across all sessions.
---

# Signal

Single entry point for task management. Every invocation syncs first, then asks what the user wants.

## Trigger

- User invokes `/signal`
- User says "work", "let's go", "what's next", "status", "check tasks", or similar

## Main flow

Every `/signal` invocation runs the same flow:

### 1. Sync

a. **Resolve today's task file:**
   - Check if `~/.claude/signal/<today>-tasks.md` exists.
   - If not, find the most recent `*-tasks.md`: `ls -t ~/.claude/signal/*-tasks.md | head -1`
   - Copy it to `~/.claude/signal/<today>-tasks.md`.
   - Update the `Updated:` date line to today.

b. **Read context:** `~/.claude/signal/context.md`

c. **Check in-progress tasks via session logs:** For each task marked `(in progress)` that has a repo, run:
   ```bash
   python3 ~/.claude/signal/check-session.py --project <name> --keywords "kw1,kw2" --top 3 --tail 10
   ```
   Pick 2-3 task-specific keywords. Use `--top 3` minimum — multiple tasks in the same project can shadow each other if only top 1 is returned.

d. **Check connected tools:** For ALL tasks (not just code tasks), check for updates via:
   - **Gmail:** search for recent emails related to the task (from relevant contacts, by subject)
   - **WhatsApp:** always sync default first (`whatsapp_sync` with no params — syncs contacts + chats). Then for specific people relevant to tasks, sync their messages (`whatsapp_sync` with `what="messages"` and `chats=["Name"]`), then read with `whatsapp_get_messages`.
   - **git log:** check recent commits in relevant repos
   This is not optional — always check Gmail and WhatsApp during sync.

e. **Update task states** based on what you find — mark as `(done)`, `(failed: reason)`, or leave as `(in progress)`.

### 2. Show summary

Show the user all tasks with current states.

**For blocked tasks:** always suggest a concrete unblocking action. "Waiting" is not a final state — there's always something that can be done to push forward (follow up, escalate, find an alternative). Think about what the user can do NOW to move the task forward.

**Sending an email / message is not completing a task.** The task is solving the underlying problem. Sending an email is a step. Track the actual outcome, not the action taken.

### 3. Ask

> Want to add notebook notes, or work on something?

- If the user has notebook notes (photo or verbal): run the **intake flow**.
- If the user wants to work: run the **work flow**.

## Intake flow

When the user provides tasks (photo or verbal):

1. Parse every task into a flat list. No categories, no structure beyond what they gave.
2. Look for starred, circled, numbered, or otherwise marked items — those are the signal. If nothing is marked, ask which 1-2 are the focus.
3. For each signal task, ask just enough to act on it (where, what, done looks like). 2-3 questions max per task.
4. Save to today's task file.

## Work flow

When the user picks a task:

1. Dispatch:
   - **Code task with a repo:** spawn a new terminal tab, passing task context as the prompt.
   - **Non-code task:** work on it directly from the current session using Gmail, WhatsApp, web search, or ask the user.
2. Update task states as work progresses.

### Spawning terminals

Use the launcher script at `~/.claude/signal/launch.ps1`:

```bash
wt.exe -w 0 new-tab --title "<task name>" -p "PowerShell" -- pwsh.exe -NoExit -File "C:\Users\franc\.claude\signal\launch.ps1" -dir "<repo path>" -prompt "<task context>"
```

The prompt should include all relevant context: what the task is, what repo, what "done" looks like, and any prior progress or decisions.

If the task involves researching libraries, APIs, or external code, include this in the prompt:

> Use /nia when you need to verify assumptions about libraries or APIs. Flow: first run list repos/docs to see what's indexed, then search packages or grep for the specific behavior you need to verify.

When spawning, ALWAYS append to the prompt:

> When you finish this task:
> 1. Push your changes with git add . && git commit && git push.
> 2. Update today's task file in ~/.claude/signal/ (named YYYY-MM-DD-tasks.md) — find the relevant task line and APPEND your context (root cause, what was done, what's left) after the existing text. Do NOT replace the original task description — keep it for traceability. Change the state to (done) or (failed: reason).

## Daily task files

- File naming: `~/.claude/signal/YYYY-MM-DD-tasks.md`
- Always read and write to **today's file**. Never edit past days' files.
- Past files are the traceability log — they show what was on the list each day.

## Task states

Append state at the end of a task line in parentheses:

- `(in progress)` — work started, not finished
- `(blocked: reason)` — waiting on something external
- `(needs decision: question)` — Claude can't proceed without user input
- `(failed: what went wrong)` — attempted but stuck
- `(done)` — completed

## File format

```markdown
# Tasks

Updated: YYYY-MM-DD

## Projects

| Project | Session path | Notes |
|---|---|---|
| repo_name | /path/to/repo | description |

* signal task — repo: folder — context — done when X (state)
- regular task
- another task (done)
```

Rules:
- `*` prefix = signal (current focus). Only 1-2 of these.
- `-` prefix = everything else.
- Each signal task gets context separated by ` — `.
- Non-signal tasks are just raw text unless they have state.
- No categories, no headers beyond `# Tasks` and `## Projects`, no nesting.

## Persisting context

Update today's task file whenever:
- A task is completed, fails, or gets blocked
- New context is learned about a task (progress, decisions, blockers)
- The user provides new tasks or re-prioritizes

Always update the `Updated:` date line.

## Context file

`~/.claude/signal/context.md` stores facts Claude needs to act without asking: people, accounts, companies, tools.

Update `context.md` whenever new facts are learned.

## Tools

- **check-session.py** — `~/.claude/signal/check-session.py` — searches Claude Code session logs for task progress. Maps project names to session dirs via `projects.json`.
- **projects.json** — `~/.claude/signal/projects.json` — project name to filesystem paths. Script converts paths to Claude Code dir names at runtime.
- **launch.ps1** — `~/.claude/signal/launch.ps1` — spawns Claude Code in a new terminal tab.
