---
name: compile-wiki
description: Compile the Obsidian wiki/ layer from raw/ atomic notes. Diffs which notes have not yet been cited in any wiki sources[], routes each into a new or existing concept article, writes provenance-carrying markdown, and lints the result against wiki_graph(). Use when the user says "compile", "compile the wiki", "rebuild concepts", "compile-wiki", or invokes /compile-wiki. Requires the obsidian MCP (raw_graph, wiki_graph, read, write).
---

# compile-wiki

Run one compile pass over the Obsidian books KB. This skill is a map-reduce over atomic notes: each note is an observation, each concept article integrates many. `sources[]` in concept frontmatter IS the coverage ledger — no separate flag.

## Prerequisites

- The `obsidian` MCP server is connected. If it isn't, stop and tell the user to start Obsidian (with the Local REST API plugin enabled) and reconnect the MCP.
- The vault follows the layout in `mcps/obsidian/README.md`: `raw/<book>/notes/<slug>.md` atomic notes, `wiki/concepts/<slug>.md` compiled articles, `wiki/index.md` Map of Content.

## The loop

```
1. SCAN       raw_graph() + wiki_graph()
2. DIFF       uncompiled = atomic notes not cited in any wiki sources[]
3. ROUTE      per note: extend an existing concept OR start a new one
4. WRITE      read → synthesize → write (preserve frontmatter)
5. STITCH     update wiki/index.md + related: cross-links
6. LINT       wiki_graph() — fix ghost links, link orphan concepts
```

## 1. Scan

Call both graphs in parallel:

- `raw_graph()` — every `note` node + its frontmatter + body links.
- `wiki_graph()` — every `concept` / `book-summary` / `index` node, with `sources: [[...]]` already resolved as edges into `raw/` (the server builds wiki with `link_roots=["raw", "attachments"]`).

If `wiki/` is empty (zero nodes), this is a cold start — every atomic note is uncompiled. Proceed to step 2.

## 2. Diff

Build two sets:

- `atomic_notes` = every node from `raw_graph()` with `type: "note"`.
- `cited_notes` = every edge from `wiki_graph()` with `kind: "frontmatter"` whose `to` lands under `raw/.../notes/<slug>.md`.

Then `uncompiled = atomic_notes - cited_notes`.

If `uncompiled` is empty: report "wiki is up to date — N concepts cover all M atomic notes, 0 uncompiled" and stop. Do NOT invent new work.

## 3. Route — extend vs. new

For each note in `uncompiled`, decide one of two things:

- **Extend an existing concept** — if a current `wiki/concepts/<slug>.md` topically owns this note (refines, deepens, qualifies, or contradicts it). Signals:
  - The concept's title / heading directly names the note's subject.
  - The note already wikilinks sideways to a raw note that the concept cites.
- **Start a new concept** — if no existing article fits. Pick a stable, lowercase, hyphenated slug derived from the concept name (not the source note's slug). One concept = one article.

When in doubt between extend and new, prefer extend — atomic notes are observations; concepts integrate many.

## 4. Write (read-modify-write, frontmatter intact)

`write` is a FULL OVERWRITE. Never emit a concept file without first reading it.

**Extend path** — for an existing concept `wiki/concepts/<slug>.md`:

1. `read(path)` → get current text.
2. Parse frontmatter mentally. Integrate the new note's content into the body prose (don't append raw quotes — synthesize).
3. Append the source note's FULL slug to `sources:` — e.g. `[[inyectividad-y-predecesores]]`, NOT `[[inyectividad]]`. Basename collisions with a concept slug would resolve sideways (into the concept itself) instead of down into `raw/`.
4. Bump `updated: YYYY-MM-DD` (today's date).
5. If a new sibling concept emerges from the integration, add it to `related:`.
6. `write(path, content=<full new text>)`.

**New path** — for a fresh `wiki/concepts/<new-slug>.md`:

```yaml
---
type: concept
sources: ["[[<atomic-note-full-slug>]]"]
related: []
updated: YYYY-MM-DD
---

# <Concept Title>

<synthesized prose — explain the concept, then weave in observations
from the source note. Match the language of the source notes (Spanish
sources → Spanish concept; English → English).>
```

Then `write("wiki/concepts/<new-slug>.md", content=...)`.

**Match the source language.** If the raw note is in Spanish, the concept article is in Spanish. Don't translate user prose.

## 5. Stitch

After all writes in step 4:

- **`wiki/index.md`** — read it, add a wikilink to any new concept under the appropriate section heading (e.g. `## Matemáticas`, `## Meta / aprendizaje`). If the section doesn't exist, create it. Preserve existing entries.
- **`related:` cross-links** — for each new or extended concept, pick 1–3 sibling concepts and add them to its `related:` array. Mirror the edge on the sibling's side (read the sibling, add the new concept to its `related:`, write back). This builds the lateral graph between concepts.

## 6. Lint

Call `wiki_graph()` one more time. Walk the edge set:

- **Ghost links** — any edge with `target_exists: false`. Fix the slug (most common cause: bare basename that doesn't match any file). Re-write the offending file.
- **Sideways provenance** — any edge from `wiki/concepts/<a>.md` to `wiki/concepts/<b>.md` via `kind: "frontmatter"` with key `sources`. That's a basename-collision bug: the concept is citing another concept instead of the raw note. Fix by replacing the source entry with the FULL atomic-note slug.
- **Orphan concepts** — any `concept` node with zero incoming `wikilink` or `frontmatter` edges from `wiki/index.md` or other concepts. Add it to `wiki/index.md` or link it from a related concept.
- **Provenance sanity** — every `wiki/concepts/<slug>.md` must have ≥1 edge into `raw/.../notes/...`. If it doesn't, the `sources[]` is wrong.

Re-lint until clean.

## Report

End the pass with a short summary in this exact shape:

```
Compile pass complete.

  Concepts touched:
    + wiki/concepts/<new-slug>.md       (new, sources: [<note-slugs>])
    ~ wiki/concepts/<existing-slug>.md  (extended, +N sources)

  Coverage:
    atomic notes: <total>
    cited:        <count>
    uncompiled:   0  (or list the slugs if any deliberately skipped)

  Lint (wiki_graph):
    nodes: <N>   edges: <M>   ghosts: 0
```

If any step failed (MCP disconnect, write error, lint not clean after one fix pass), stop and report the failure rather than silently glossing over it.

## Rules

- **NEVER touch `raw/`.** This skill only writes under `wiki/`. `raw/` is the source of truth.
- **NEVER overwrite a concept without reading it first.** `write` is full overwrite — read, modify in memory, write back.
- **NEVER paraphrase user prose from raw notes.** Synthesize the concept in your own words; if you need to quote, quote verbatim.
- **NEVER use a bare basename in `sources[]`** when there's any chance of collision with a concept slug. Use the full atomic-note slug.
- **NEVER create top-level folders.** Only `raw/`, `wiki/`, `attachments/`.
- **NEVER invent compile work.** If `uncompiled` is empty, report "up to date" and stop.
- **Match the language** of the source notes in the concept article.
- **One concept = one article.** If a note refines an existing concept, extend it; don't fork a near-duplicate.
- **Confirm with the user** before writing if the uncompiled set is large (≥5 notes) or if any routing decision is ambiguous. For small passes (1–3 notes), proceed.
