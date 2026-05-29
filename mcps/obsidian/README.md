# Obsidian MCP — books knowledge base

An MCP server over an Obsidian vault that holds a personal knowledge base of
math + CS books. It follows the "LLM knowledge base" pattern: raw source
material is ingested into `raw/`, and an LLM incrementally compiles a `wiki/`
of concept articles on top of it. The LLM reads and writes the markdown; you
read it in Obsidian.

The server talks to the vault through the
[coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api)
plugin (HTTPS + bearer token on `127.0.0.1:27124`).

## Architecture

Three top-level folders, by design — nothing else:

```
raw/                              # ingest layer — sources + your notes
  <book>/
    <book>.md                     # hub: frontmatter + nav callout + summary
    *.pdf                         # sources: textbook, solutions, errata, ...
    notes.md                      # notes INDEX (frontmatter `book: [[X]]`)
    notes/<slug>.md               # atomic notes (`parent: [[notes]]`)
  notes/                          # a "book" that isn't a book — meta notes
    notes.md
    notes/<slug>.md

attachments/<book>/*.png|jpg      # screenshots, diagrams

wiki/                             # compiled layer — LLM-written (see Roadmap)
```

### Notes model — atomic, Zettelkasten-style

- `notes.md` is an **index** node: minimal body, `book: [[X]]` in frontmatter.
- Each thought is an **atomic note** at `raw/<book>/notes/<slug>.md` whose
  frontmatter is `parent: [[notes]]` only. The book is reached transitively
  (`note → notes → book`), so there's no direct note→book edge.
- Obsidian surfaces children as backlinks automatically — `notes.md` never has
  to list them.

### Graph node types

`raw_graph()` classifies every node by path shape:

| type           | path shape                          |
|----------------|-------------------------------------|
| `hub`          | `raw/<book>/<book>.md`              |
| `notes`        | `raw/<book>/notes.md`               |
| `note`         | `raw/<book>/notes/<slug>.md`        |
| `index`        | `wiki/index.md`                     |
| `concept`      | `wiki/concepts/<slug>.md`           |
| `book-summary` | `wiki/books/<slug>.md`              |
| `pdf`          | `*.pdf`                             |
| `image`        | `*.png .jpg .jpeg .webp .svg .gif`  |
| `other_md`     | any other `.md`                     |
| `other`        | anything else                       |

Edges come from wikilinks, embeds, and `[[...]]` strings inside frontmatter.
Links that resolve to nothing are flagged `target_exists: false` (ghost links).

## Tools

| Tool | Signature | What it does |
|------|-----------|--------------|
| `raw_graph` | `raw_graph()` | Whole graph of `raw/` — nodes (md/pdf/image) + edges (wikilink/embed/frontmatter), with ghost-link detection. Call this first to orient. |
| `wiki_graph` | `wiki_graph()` | Graph of `wiki/` (the compiled layer). Same shape; nodes typed `index`/`concept`/`book-summary`. Links resolve against `raw/` too, so a concept's `sources: [[note]]` shows as a real provenance edge into `raw/`. Use it to lint the wiki. |
| `read` | `read(path)` | Read one `.md` file. Markdown only — PDFs are not readable. |
| `write` | `write(path, content="", image_path=None)` | Write a file. `.md` → pass `content`. `.png/.jpg/.jpeg/.webp` → pass `image_path` (absolute local path; the server reads the bytes and uploads). Full overwrite. |

PDFs appear in the graph as nodes (with page count + `extractable` from the
sibling hub's `sources[]`) so the LLM knows they exist, but `read` is `.md`-only
by design — the markdown layer is the human↔AI channel.

## Setup

### 1. Obsidian Local REST API plugin

1. In Obsidian: **Settings → Community plugins → Browse**, install **Local REST API**.
2. Enable it. It serves HTTPS on `127.0.0.1:27124` with a self-signed cert
   (the client sets `verify=False`).
3. Copy the API key from the plugin's settings.

### 2. Credentials

Add to the repo-root `.env` (gitignored):

```
OBSIDIAN_API_KEY=<key from the plugin>
# optional overrides:
# OBSIDIAN_HOST=127.0.0.1
# OBSIDIAN_PORT=27124
```

### 3. Register with Claude Code

```bash
claude mcp add -s user obsidian -- uv run --directory /path/to/mcp_servers/mcps/obsidian fastmcp run server.py
```

Or with Droid:

```bash
droid mcp add obsidian "uv run --directory /path/to/mcp_servers/mcps/obsidian fastmcp run server.py"
```

Obsidian must be **running** with the REST API plugin enabled for the server to
connect (otherwise calls fail with connection-refused on `127.0.0.1:27124`).

## Behavioral rules (enforced via the server's `instructions`)

- **Always start with `raw_graph`.** Don't read blindly — the graph tells you
  what exists, the node types, and which links are ghosts.
- **Append = read-modify-write.** `write` is a full overwrite; to extend a note,
  read it, edit in memory, write the whole thing back.
- **Preserve frontmatter.** It's the queryable schema and the edge backbone
  (`parent`, `book`, `status`, `sources`, `tags`). Never silently mutate it.
- **Wikilink hygiene.** Use exact basenames from the graph; don't invent ghosts.
- **No new top-level folders.** Only `raw/`, `wiki/`, `attachments/`.
- **Confirm before write** unless the user pre-authorized ("just log this").

## Layout

```
server.py            # FastMCP server — 3 tools, thin wrappers, instructions block
obsidian_client.py   # REST client + frontmatter parser + wikilink resolver + graph builder
pyproject.toml       # fastmcp 3.1.1, requests, pyyaml, pypdf, ...
logs/                # rotating server log
```

## The `wiki/` layer — compile + lint

`raw/` (ingest) is in place, and the **tooling** for the compiled layer now
exists: `wiki_graph()` plus the `wiki/` convention below. What's left is to run
compile passes as the note count grows.

Structure (LLM-written — you don't hand-author it):

```
wiki/
  index.md                 # Map of Content — entry point for Q&A
  concepts/<slug>.md       # one article per concept, synthesized from notes
  books/<slug>.md          # per-book compiled summary
```

Each concept article carries provenance so it traces back to `raw/`:

```yaml
---
type: concept
sources: ["[[inyectividad-y-predecesores]]"]   # raw notes compiled from
related: ["[[induccion-matematica]]"]
updated: 2026-05-25
---
```

**Compile loop** (on explicit "compile" / "rebuild wiki"):

1. `raw_graph()` + `wiki_graph()`.
2. Uncompiled set = atomic notes not cited in any wiki `sources[]`.
3. Per note: extend an existing concept (read → rewrite) or start a new one.
   One concept = one article; notes are atomic, concepts integrate many.
4. Update `wiki/index.md` and `related:` cross-links.
5. Lint with `wiki_graph()`: fix ghost links, link orphan concepts.

`wiki/` is derived, regenerable data; `raw/` is the source of truth. `sources[]`
doubles as the coverage ledger — no separate "compiled" flag to drift. Q&A reads
`wiki/index.md`, navigates to the relevant articles, and answers from them.
