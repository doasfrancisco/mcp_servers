---
name: sources
description: Set up nia.md at the current project root. Analyzes dependency manifests, filters to the libraries worth binding, resolves them against Nia, and writes nia.md using a fixed template. Then asks if the user wants to add docs or other repos. Use when the user says "set up sources", "create nia.md", "bind nia to this project", or invokes /sources.
---

# sources

Generate `nia.md` at the project root so future Claude sessions know which Nia-indexed sources map to this project's dependencies.

## 1. Check for an existing nia.md

Look for `nia.md` (case-insensitive) at the project root. If it exists, read it and tell the user it's already set up. Ask if they want to **refresh** it (regenerate from current dependencies). If they say no, stop.

## 2. Find dependency manifests

Scan the project root up to depth 4, **excluding** `node_modules/`, `.venv/`, `venv/`, `__pycache__/`, `dist/`, `build/`:

- `pyproject.toml` — read `[project].dependencies` (NOT `[tool.*]` dev groups)
- `requirements.txt` — one dep per line
- `package.json` — read `dependencies` only, NOT `devDependencies`
- `Cargo.toml` — `[dependencies]`
- `go.mod` — `require` block

In monorepos, collect the **union** of runtime deps across every manifest. Strip version specifiers and extras — you only need names.

## 3. Filter to the deps worth binding

Not every dep deserves a Nia source. The goal is a short list of libraries that define the project's problem domain — the ones you'd look up API docs for in a typical session.

**Skip these categories:**

- **Config/env**: `python-dotenv`, `dotenv`, `configparser`, `pyyaml`, `toml`
- **Basic HTTP primitives**: `requests`, `urllib3`, `httpx`, `aiohttp`, `axios`, `node-fetch`, `got`
- **Tiny utilities**: `pillow`, `pystray`, `cors`, `body-parser`, `zod`, `pydantic`, `joi`, `ajv`
- **Dev tooling**: `pytest`, `jest`, `eslint`, `prettier`, `typescript`, `tsx`, `nodemon`, `vitest`
- **Generic helpers**: `lodash`, `moment`, `dayjs`, `uuid`, `chalk`, `ms`

**Keep** frameworks, SDKs, platform libraries, and anything domain-specific. Example from this repo: keep `fastmcp`, `google-api-python-client`, `spotipy`, `beeper-desktop-api`, `@modelcontextprotocol/sdk`, `whatsapp-web.js`, `electron`, `express`, `glpi`. Skip `python-dotenv`, `httpx`, `pillow`, `pystray`, `cors`, `zod`, `urllib3`.

When in doubt, **keep** it — the annotated resolution results in step 4 will tell you which keeps are actually indexed, and the user can drop rows before the file is written.

**Do NOT show the keep list and ask for approval yet.** Go straight to step 4 and resolve the whole keep list against Nia first — the user needs to see which are indexed before they can decide what to drop.

## 4. Resolve the keep list against Nia, then present an annotated table

```bash
# One-time dump — cache the full indexed-sources catalog
nia sources list --all > /tmp/nia_sources.txt
```

Then do **a single grep for all deps at once** using a regex alternation. Build the pattern by joining every dep with `|`:

```bash
# Replace <dep1>|<dep2>|... with your actual keep list
DEPS="convex|next|fastmcp|express|electron|spotipy|boto3|PyMuPDF|pyproj"
grep -iE -B 3 -A 1 "^  (identifier|display_name): .*(${DEPS})" /tmp/nia_sources.txt
```

One invocation returns every hit across the full keep list — no per-dep loop, no parallel calls, no cancellations.

Rules for interpreting matches:

- **Multiple hits for one dep is common and expected** — e.g. `convex` has both `https://docs.convex.dev/` (documentation) and `get-convex/convex-backend` (repository). Show the user all hits per dep and let them pick the right one (or keep both, with different `Type`).
- **Pick `status: indexed` or `ready` over `status: processing`** — processing sources aren't searchable yet.
- **Strip any branch suffix** from the `identifier` before writing (`:main`, `:master`, `:trunk` — these only appear in `display_name`, but double-check).
- **No hits** for a dep → classify as **not indexed**. Suggest `nia repos index <guess-owner/repo>` with the best-guess owner/repo (standard pattern: `<org>/<pkgname>` for JS, `<owner>/<pkgname>` for Python on PyPI).

Then present **one annotated table** to the user using this exact shape — one row per dep, with the Link column so they can click through and confirm the resolution is correct:

```
| Dep | Status | Nia identifier | Link |
|---|---|---|---|
| <dep-name> | ✓ indexed | <owner/repo> | https://github.com/<owner/repo> |
| <dep-name> | ✗ not indexed | — (run `nia repos index <guess-owner/repo>`) | — |
```

Rules for the Link column:

- **Repositories** → `https://github.com/<identifier>` (the identifier is already `owner/repo`).
- **Documentation** → use the `identifier` verbatim (it's already the docs URL).
- **Research papers** → use the arXiv URL from the resolve result.
- **Not indexed** → leave as `—`.

Also show the **skip list** below the table for transparency (e.g. `Skipped: <dep-a>, <dep-b> (reason)`).

Now ask the user: "Keep all indexed rows? Drop any? Index the missing ones before writing, or skip them?"

Wait for their answer before writing nia.md.

## 5. Write nia.md

Use this **exact template** at the project root. Replace only the `<project-name>` token and the rows of the Sources table. **Do not change the Rules section. Do not change the Examples section's docs lines (the `nia sources resolve "https://platform.claude.com/docs"` block and the `--docs` arg in the multi-source query).**

````markdown
# Nia sources for <project-name>

## Rules

- **Never pipe `nia` output through `head -N` or `tail -N`.** The output can be 2000+ lines. You MUST read ALL of it. If the output is split across chunks, read every chunk before proceeding. Missing a single source leads to wrong follow-up searches and wasted user time.
- **If the source is a package/library, always ask how to install it** (pip name, Python/Node version, any extras). E.g. `"how do I install X - pip name, python version, async extras?"`

## Sources

| Dep | Nia identifier | Type |
|---|---|---|
| `<dep>` | `<owner/repo>` | repository |

## Examples

```bash
nia search query "<topic tied to one of this project's repos>" --repos <owner/repo>
nia search query "<another topic>" --repos <another-repo>
nia repos tree <one-of-the-repos>
nia repos read <one-of-the-repos> <plausible-file-path>
nia repos grep <one-of-the-repos> "<plausible-symbol>"

nia sources resolve "https://platform.claude.com/docs" --type documentation
nia sources tree <UUID>
nia sources read <UUID> build-with-claude/prompt-caching.md
nia sources grep <UUID> "cache_control"
```

### Multi-source query

```bash
# Example
nia search query "<cross-cutting topic>" \
  --repos <repo-a>,<repo-b> \
  --docs "https://platform.claude.com/docs"
```
````

For the five code-example lines at the top of the bash block, pick queries that realistically exercise this project's repos — same *shape* as the examples above, just different sources. Don't invent file paths; use ones you've actually seen, or keep the command at the tree/grep level where no path is needed.

## 6. Ask about extras

Once nia.md is written, ask the user:

> Do you want to add any other sources? For example docs sites (e.g. `https://docs.stripe.com`), or other repos you reference often but aren't in the dep manifest.

For each extra:

- **Docs URL**: `nia sources resolve "<url>" --type documentation`. If it resolves, append it to the Sources table with Type `documentation`. If not, suggest `nia sources index <url>`.
- **Repo**: `nia sources resolve "<owner/repo>"`. If not indexed, suggest `nia repos index <owner/repo>`.

Append each resolved extra to the Sources table with its correct `Type`.

## Commands to list and filter Nia sources

**Preferred pattern — dump once, grep many.** One 4s network call, then unlimited local lookups.

```bash
# Dump the full indexed catalog to a local file
nia sources list --all > /tmp/nia_sources.txt

# Grep for any dep — matches identifier OR display_name, with 3 lines of leading context
grep -iE -B 3 -A 1 "^  identifier: .*<dep>|^  display_name: .*<dep>" /tmp/nia_sources.txt

# Restrict to a single type
nia sources list --type repository --all > /tmp/nia_repos.txt
nia sources list --type documentation --all > /tmp/nia_docs.txt
```

Never pipe these through `head` / `tail` — at 1000+ sources, pagination misses are the #1 cause of wrong source picks. Redirect to a file and grep it instead.

Fallback commands (only when the grep-the-dump flow above isn't available):

```bash
# Resolve a single known identifier to its Nia id (slow; one round-trip per call)
nia sources resolve "<name>"
nia sources resolve "<owner/repo>"
nia sources resolve "<url>" --type documentation

# Index a new source
nia repos index <owner/repo>
nia sources index <root-doc-url>
```

## Rules

- NEVER include `devDependencies` — runtime deps only.
- NEVER include every dep — filter with step 3 first.
- NEVER pause for approval between steps 3 and 4. Filter, then resolve the whole keep list up front, THEN present an annotated table so the user can make an informed keep/drop call with indexing status visible.
- NEVER call `nia sources resolve` once per dep in a loop. Always dump `nia sources list --all` to a file first, then grep locally. The per-dep resolver is slow and frequently cancels sibling parallel calls.
- NEVER modify the Rules section of nia.md or the example lines.
- NEVER pipe `nia sources list` / `nia repos list` through `head` or `tail`. Read the whole output.
- NEVER commit nia.md without showing the user the final contents.
- If a dep doesn't resolve, list it at the end as "Unresolved — may need `nia repos index <owner/repo>`" so the user can decide.
- Strip `:main` / `:master` / `:trunk` branch suffixes from identifiers before writing.
