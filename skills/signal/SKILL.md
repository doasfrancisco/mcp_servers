---
name: signal
description: Task intake and context tracking. Use when the user shows a photo of handwritten tasks, says "read my tasks", invokes /signal, or asks what they should work on. Reads task photos, asks for context on starred items, and saves working context to ~/.claude/signal/tasks.md so Claude knows what's in progress across all sessions regardless of working directory.
---

# Signal

Read the user's tasks, clarify the important ones, and persist context so every future session starts informed.

## Trigger

The user does one of:
- Shows a photo of handwritten tasks
- Says "read my tasks" or "what should I work on"
- Invokes `/signal`

## Flow

### 1. Intake

If the user provides a photo, read it. If they describe tasks verbally, listen.

Parse every task into a flat list. Do not categorize. Do not add structure they didn't ask for.

### 2. Identify signal

Look for starred, circled, numbered, or otherwise marked items — those are the signal. If nothing is marked, ask:

> Which of these are the 1-2 most important for today?

### 3. Ask for context

For each signal task, ask just enough to act on it:

- **Where?** Which repo / folder / project?
- **What?** What's the problem or goal?
- **Done looks like?** How do we know it's finished?

Keep it conversational. Don't interrogate — 2-3 questions max per task.

### 4. Save context

Create `~/.claude/signal/` if it doesn't exist. This is a global location — all sessions read from the same file regardless of working directory.

Write or update `~/.claude/signal/tasks.md` with this format:

```markdown
# Tasks

Updated: YYYY-MM-DD

* task description — repo: folder_name — what needs to happen — done when X
* another task — repo: folder_name — context — done when Y
- regular task from the list (no star = not the focus today)
- another regular task
```

Rules:
- `*` prefix = signal (today's focus). Only 1-2 of these.
- `-` prefix = everything else from the list.
- Each signal task is one line with context separated by ` — `.
- Non-signal tasks are just the raw text, no extra context needed.
- No categories, no headers beyond `# Tasks`, no nesting.

### 5. Confirm and start

Show the user what was saved. Then ask:

> Ready to start on [signal task]?

If yes, begin working on it immediately.

## Reading context in future sessions

At the start of any session, if `~/.claude/signal/tasks.md` exists, read it. You now know:
- What's in progress (starred items)
- What else is on the list

If the user starts talking about a task that's in the file, you already have context. If they show a new photo, re-run the full flow and overwrite the file.
