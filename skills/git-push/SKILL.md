---
name: git-push
description: Safely commit and push changes. Audits .gitignore for sensitive files, stages with git add ., writes a conventional commit (what + why), creates a GitHub repo via gh if none exists, and pushes. Use when the user says "push", "ship it", "commit and push", or invokes /git-push.
---

# git-push

Safely commit and push the current changes. Every run follows this exact sequence:

## 1. Safety check

Run `git status` to see what will be staged. Review the actual file list for:

- **Secrets** — `.env`, `.pem`, `.key`, credentials, tokens, API keys
- **Internal data** — data dumps, migration exports, board exports, JSON/CSV with names/tasks/internal info, database exports. Any folder that looks like a one-off dump (e.g. `*-migration/`, `*-export/`, `*-dump/`) is a red flag.
- **Large binaries** — blobs, images, compiled files that don't belong in git
- **Files that should be gitignored** — check if the repo is public, and whether the file contains anything that shouldn't be on GitHub

Only stop if you find a **real problem**. Do NOT theorize about what .gitignore *could* be missing — check the actual files. If every file in the diff is safe, move on silently.

## 2. Initialize git if missing

If `.git/` does not exist, run `git init` and continue. If it exists, skip.

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

If there is nothing to commit yet (empty repo), create an initial commit after staging so step 5's `gh repo create --push` has something to push.

## 5. Ensure a GitHub remote exists

Run `git remote -v`. Three cases:

**a) A remote is already set** → skip to step 6.

**b) No remote at all** → create one on GitHub using `gh`:

1. Verify auth: `gh auth status`. If not logged in, stop and ask the user to run `gh auth login`.
2. Pick a repo name. Default: the current directory's basename. Confirm with the user before creating.
3. Default to **private** unless the user explicitly says public. Creating a public repo without asking is a mistake — code can contain secrets, half-finished work, or internal context the user didn't mean to publish.
4. Create and push in one call:

   ```bash
   gh repo create <name> --source=. --private --push
   ```

   This creates the GitHub repo, wires up `origin`, and pushes the current branch with upstream tracking. Do not run `git push` again afterward.

**c) Remote exists but the current branch has no upstream** → push with `-u`:

```bash
git push -u origin <current-branch>
```

## 6. Push

If step 5 already pushed (cases b and c), skip this step. Otherwise:

```bash
git push
```

## Rules

- NEVER skip any step.
- NEVER push if the audit flagged something — resolve it first.
- NEVER add a Co-Authored-By line.
- NEVER create a public repo without explicit user consent. Default to private.
- NEVER guess the repo name — confirm with the user before `gh repo create`.
- If there are no changes to commit and the remote is already up to date, say so and stop.
- If a pre-commit hook fails, fix the issue and create a NEW commit (don't amend).
