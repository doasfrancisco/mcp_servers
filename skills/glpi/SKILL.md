---
name: glpi
description: Analyze GLPI tickets at depth — pick the right MCP tool, pull full ticket content in one shot, and delegate large-result-set analysis to an Explore agent instead of writing Python. Use when the user asks about GLPI tickets, requests patterns/themes across tickets, asks "what's happening with X", "find anything related to Y", "tickets this week/month", or invokes /glpi.
---

# glpi

How to query the GLPI MCP and deliver in-depth analysis without burning the user's context or resorting to Python scripts.

## Tool selection

The GLPI MCP has several tools. Pick the one that matches the question — don't default to the lowest-level one.

| Question shape | Tool | Notes |
|---|---|---|
| "tickets today" / "tickets this week" / "by category" / "by assignee" | `glpi_search_tickets` | High-level filter API. Name-based filters (category, assignee, requester). Returns short fields only — no content. |
| "tickets at risk of SLA breach" | `glpi_search_tickets` with `due_within_hours=24 status="open"` | Built for this. |
| Deep analysis across many tickets (need the description text) | `glpi_search` with `forcedisplay=[2,1,7,12,15,21]` | Field 21 is the content. Add 3/14/19/4/5 if you need priority/type/closedate/requester/assignee too. |
| Full context on ONE ticket (timeline, followups, tasks, solutions, documents, logs) | `glpi_get_ticket_full` | One call replaces 6+. Never call `glpi_get_itil_timeline` alongside it — `timeline` is already inlined. |
| Knowledge base lookup | `glpi_search_knowbase` | |
| User context (who they are, groups, location) | `glpi_get_user_context` | |
| What search fields exist on an itemtype | `glpi_list_search_options` | Only when an obscure field ID is needed. |
| Download an attachment | `glpi_download_document` | |

**Field ID legend for Tickets** (memorize these — they show up in every `data` row with numeric keys):

- `1` = name (title) · `2` = id · `3` = priority · `4` = requester · `5` = assignee
- `7` = category · `12` = status · `14` = type · `15` = date_creation · `19` = closedate · `21` = content

**Status codes** (use the emoji when presenting to the user):

- `1` New 🆕 · `2` Assigned 👤 · `3` Planned 📅 · `4` Waiting ⏸️ · `5` Solved ✅ · `6` Closed 🔒

## Rule: never write Python to mine a saved GLPI dump

When a GLPI tool returns more data than fits in context, the harness saves it to disk and returns a file path. **Do not write a Python script, `python -c` one-liner, or `jq` pipeline to analyze that file.** Spawn an Explore agent with the file path and the question.

Python-on-saved-files is unnecessary ceremony. The agent path is shorter, cleaner, and keeps raw JSON out of the main context. The only justified exception is a precise numeric aggregate across thousands of rows where determinism matters — and even then, say so explicitly first.

## Step-by-step for deep analysis across many tickets

Use this flow when the user asks "find anything related to X in GLPI" or "what's going on with Y this month" — anything that needs the ticket **descriptions**, not just titles.

### 1. Pull the data in ONE filtered call

Use `glpi_search` with criteria + `forcedisplay` that includes field 21 (content). Filter at the MCP layer — date range, category, text — don't pull everything and filter later.

Example criteria:

```json
[
  {"field": 7,  "searchtype": "contains", "value": "ANA Prevention"},
  {"link": "AND", "field": 15, "searchtype": "morethan", "value": "2026-04-01 00:00:00"},
  {"link": "AND", "field": 15, "searchtype": "lessthan", "value": "2026-05-01 00:00:00"}
]
```

With `forcedisplay=[2,1,7,12,15,21]`, `sort=15`, `order="ASC"`, and a range big enough to cover the full result set (`"0-299"` or bigger).

Expect the response to exceed token limits and save to disk. That's fine — note the file path.

### 2. Spawn an Explore agent on the saved file

`Agent(subagent_type=Explore)` with a self-contained prompt that includes:

- **File path** (absolute).
- **Schema:** outer `{"result": "<stringified inner JSON>"}`. Inner `.data` is the row list. Each row uses string-keyed numeric fields.
- **Field legend** (`"2"`=id, `"1"`=title, `"7"`=category, `"12"`=status, `"15"`=date, `"21"`=content).
- **Encoding gotcha:** field 21 is double-HTML-encoded. `html.unescape` twice, then strip tags. Mojibake (`�`) may appear on accented chars — the agent should be accent-tolerant in its regex.
- **The actual question** — be specific. Not "summarize this" but "find tickets mentioning a new module called X; quote verbatim; return ids".
- **Output shape:** "under 400 words", named sections, verbatim quotes for key evidence, explicit "nothing found" when applicable.

Briefing template:

```
File: <absolute path>
Schema: {"result": "<stringified inner JSON>"} → inner.data = list of N rows.
Row keys: "2"=id, "1"=title, "7"=category, "12"=status (1=new,2=assigned,3=planned,4=waiting,5=solved,6=closed), "15"=date_creation, "21"=content (double-HTML-encoded — html.unescape twice, strip tags).

Question: <specific question>.

Search signals: <list the Spanish/English patterns to look for, including synonyms and indirect phrases>.

Return (under 400 words):
1. Direct hits — id, date, status, verbatim 1–2 sentence quote.
2. Indirect hits — tickets that match synonyms / behavior descriptions (e.g. "no se puede iniciar la atención" when hunting for a Derivaciones bug).
3. What's NOT there — explicit.
4. Risk signals — blockers, data-integrity bugs, regressions.
```

### 3. Always go broad on the first pass — never narrow-first

Never run a narrow keyword scan and then "broaden if the user asks for more". The first Explore agent prompt must already hunt for:

- **Direct keyword hits** — the exact word the user asked about (e.g., "derivacion").
- **Indirect signals** — behavioral descriptions of the same problem without the keyword (e.g., "paciente no aparece", "no se puede iniciar la atención", "flujo roto", "consultorio no figura").
- **Adjacent systems** — same site, same user cluster, same time window.
- **Generic new-module / rollout signals** — "nueva funcionalidad", "nueva pantalla", "nuevo módulo", "piloto", "go-live", "implementación", "apertura del sistema".
- **Regressions from prior systems** — e.g., "antes funcionaba", "con el sistema X sí aparecía", "en Proactive esto no pasaba".

One broad pass beats two narrow passes. The user should never have to say "anything else?" to get the indirect hits.

If the user *does* ask for more after a broad pass, assume the broad pass missed a whole synonym class — go broader still, not laterally.

## Step-by-step for single-ticket deep dives

When the user asks about ONE ticket:

1. Call `glpi_get_ticket_full(ticket_id=N)`. One call. It returns expanded fields + documents + logs + notes + linked problems/changes/contracts + followups + tasks + solutions + validations + linked users/groups/assets + a sorted `timeline`.
2. **Never** fan out into `glpi_get_itil_timeline`, `get_item` for Document, `get_sub_items` for TicketFollowup, etc. Everything is already in the single response.
3. Quote verbatim from `content` and from the relevant `timeline` entries when explaining what happened.

## Presentation rules

When listing tickets to the user:

- Use the format from the MCP server instructions:
  `HH:MM [<emoji>] — <Status> — #<id> <title> · <category>`
- One ticket per line. No numbered list. Chronological order (oldest first) — the MCP already sorts this way by default.
- Use `expand_dropdowns=true` where supported so the user sees names, not IDs.
- Bold totals or category counts if the user asked for a breakdown.

When presenting analysis results from an agent:

- Quote verbatim from ticket content for key evidence. Paraphrase loses nuance.
- Include ticket ids so the user can open each in GLPI.
- Group findings by theme (module, site, user, etc.), not chronologically.
- End with a one-line risk verdict if the user asked "what's the situation" — don't volunteer it otherwise.

## Rules

- **Filter at the MCP layer.** Use `category`, `date_from`, `date_to`, `text`, `assignee`, etc. Don't pull 1000 tickets and filter locally.
- **Bundled over fan-out.** `glpi_get_ticket_full` for single tickets; `glpi_search_tickets` for filtered lists; `glpi_search` with `forcedisplay` when content is needed.
- **Never write Python to analyze a saved GLPI dump.** Spawn an Explore agent.
- **Never re-read a saved GLPI dump with the `Read` tool.** It's single-line JSON — line-based offset/limit won't chunk it.
- **Never call `glpi_get_itil_timeline` alongside `glpi_get_ticket_full`.** The timeline is inlined.
- **Always broad on the first pass.** Never narrow-then-broader. The first Explore agent prompt must already cover synonyms, indirect signals, adjacent systems, and generic rollout language. The user should not have to ask "anything else?" to get indirect hits.
- **Never paraphrase key evidence.** Verbatim quotes for anything load-bearing.
- **Never skip the emoji/status format** when listing tickets — the user scans for the emoji.
