---
name: git-push
description: Safely commit and push changes. Audits .gitignore for sensitive files, stages with git add ., writes a conventional commit (what + why), and pushes. Use when the user says "push", "ship it", "commit and push", or invokes /git-push.
---

# git-push

Safely commit and push the current changes. Every run follows this exact sequence:

## 1. Safety check

Run `git status` to see what will be staged. Review the actual file list for:

- Files that contain or look like secrets (`.env`, `.pem`, `.key`, credentials, tokens)
- Unexpectedly large binary files or data dumps
- Files that should be gitignored but aren't

Only stop if you find a **real problem** — an actual sensitive file that would be committed. Do NOT theorize about what .gitignore *could* be missing. If every file in the diff is safe, move on silently.

## 3. Stage everything

```bash
git add .
```

## 4. Write the commit message

Use **conventional commits**. No co-authoring.

Every message MUST answer both **what** changed and **why** it changed.

- `feat:` for new functionality
- `fix:` for bug fixes
- `chore:` for everything else

Bad: `feat: add repo mapping` — missing the why.
Good: `feat: add repo mapping to centralize project navigation`

Bad: `fix: update query logic` — what query? why?
Good: `fix: deduplicate subsidiary query to avoid double-counting schedules`

Bad: `chore: update dependencies` — why now?
Good: `chore: bump django to 4.2.9 to patch CVE-2024-XXXXX`

Read the diff to understand the changes, then write the message. Use a HEREDOC:

```bash
git commit -m "$(cat <<'EOF'
type: what changed and why
EOF
)"
```

## 5. Push

```bash
git push
```

If the branch has no upstream, use `git push -u origin <branch>`.

## Rules

- NEVER skip any step.
- NEVER push if the audit flagged something — resolve it first.
- NEVER add a Co-Authored-By line.
- If there are no changes to commit, say so and stop.
- If a pre-commit hook fails, fix the issue and create a NEW commit (don't amend).
