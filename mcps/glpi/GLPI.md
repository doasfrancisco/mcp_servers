# GLPI MCP — Roadmap

Ordered by priority. Each phase builds on the previous one.

## Phase 1 — Session & tickets (DONE)

- [x] Session management with token caching
- [x] Auto-refresh on 401
- [x] `glpi_tickets_today` — quick daily overview
- [x] `glpi_search` — generic search with criteria
- [x] `glpi_get_item` — single item by ID
- [x] `glpi_get_items` — list items paginated
- [x] `glpi_get_sub_items` — related items (followups, tasks, etc.)
- [x] `glpi_list_search_options` — discover searchable fields
- [x] Session/config tools (profiles, entities, full session, config)

## Phase 2 — Ticket deep-dive (DONE)

- [x] `glpi_get_itil_timeline` — merges followups + tasks + solutions + validations + logs, sorted by date. Works for Ticket, Problem, Change. Entries annotated with `_kind` and `_sub_type`. Parallel fetch via ThreadPoolExecutor.
- [x] `glpi_search_tickets` — name-based filters: `status` (new/assigned/planned/waiting/solved/closed/open), `category`, `assignee`, `requester`, `group`, `priority`, `ticket_type`, `entity`, `date_from`, `date_to`, `text`. Resolves names → IDs via cached `_resolve_user/_resolve_group/_resolve_category/_resolve_entity`.
- [x] `glpi_get_ticket_stats` — counts by status/category/priority/assignee/type/etc. Composes a bulk search (up to 5000 rows) + Python-side groupby. Humanizes status/priority/type codes. Returns `{label: count, _total, _group_by}`.
- [x] `glpi_get_ticket_full` — one call returns ticket + expanded fields + documents + logs + notes + linked problems/changes/contracts + followups + tasks + solutions + validations + linked users/groups/assets/docs. Internally parallelizes `get_item` + 8 sub_item calls.
- [x] `glpi_tickets_at_risk` — tickets with due_date within N hours AND status in (New/Assigned/Planned/Waiting). Default horizon 24h.

## Phase 3 — Assets (skipped, out of scope)

Not implemented. Use generic `glpi_get_items` / `glpi_search` for assets on demand. See "Why skipped" below.

## Phase 4 — Management & users (partial — only user context)

- [x] `glpi_get_user_context` — resolves identifier (login/realname/firstname/email/id) → user + their groups + tickets opened + tickets assigned. Parallel fetch. Replaces standalone `glpi_search_users` + `glpi_get_user_tickets` in one tool.
- [ ] `glpi_list_groups`, `glpi_list_suppliers`, `glpi_list_contracts`, `glpi_list_projects` — skipped; use generics.

## Phase 5 — Knowledge base & tools (partial)

- [x] `glpi_search_knowbase` — searches KB by title + answer. Field IDs resolved dynamically from `listSearchOptions` (names vary by GLPI version; on this instance name=6, answer=7).
- [ ] `glpi_get_knowbase_article` — not needed; use `glpi_get_item("KnowbaseItem", id)`.
- [ ] `glpi_list_reminders`, `glpi_list_saved_searches` — skipped.

## Phase 6 — Configuration & dropdowns (partial)

- [x] `glpi_list_categories` — ITILCategory tree with `completename` ("Parent > Child" path), optional per-category ticket counts.
- [x] `glpi_list_sla_ola` — parallel fetch of SLA + OLA definitions with expanded dropdowns.
- [ ] `glpi_list_locations`, `glpi_list_states`, `glpi_list_calendars` — skipped.

## Phase 7 — Advanced (partial)

- [x] `glpi_download_document` — GET `/Document/:id` with `Accept: application/octet-stream`. Returns `fastmcp.utilities.types.File(data, format, name)`. Detects GLPI's HTML error page (file-missing-on-disk case) and raises.
- [ ] `glpi_get_massive_actions`, `glpi_get_user_picture`, profile/entity switching, `getMultipleItems` — deferred.

## Why assets/networking/datacenter were skipped

Scope is "understand tickets" — the generics (`glpi_get_item`, `glpi_get_items`, `glpi_search`) already cover asset lookup on demand (e.g., `get_item("Computer", 5, with_softwares=true, with_networkports=true)`). Building 20+ specialized asset tools would bloat discovery without unlocking new workflows. Revisit only if ticket analysis hits a wall.

## Foundation added alongside Phase 2–6

- **Fixed `glpi_get_items` 400 error**: `sort` param was hardcoded to field-ID `1`; the `/:itemtype` endpoint expects a **column name** (e.g. `"id"`, `"name"`, `"date"`), not a search field ID. Changed signature to `sort: str | None = None`; only sent when explicitly provided.
- **Field name resolution in `glpi_search`**: `resolve_field(itemtype, name_or_id)` caches `listSearchOptions` per itemtype and lets criteria use `"status"` → 12 instead of requiring the numeric ID.
- **Resolver caches**: per-client `{_user_cache, _group_cache, _category_cache, _entity_cache}` keyed by identifier string → id. First call fires a contains-search; subsequent calls are O(1).
- **Static enums**: `TICKET_STATUS`, `PRIORITY_LEVEL`, `TICKET_TYPE`, `TICKET_FIELDS` at module level in `glpi_client.py`.
- **Sync + ThreadPoolExecutor** chosen over async for parallel calls — matches existing `requests` code, avoids churn, 4–9 parallel GETs per compose tool.


# Domains

┌──────────────────┬───────────┬─────────────────────────────────────────────────────────────────────────────────────────┐
  │      Domain      │ Itemtypes │                                      What's there                                       │
  ├──────────────────┼───────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ ITIL /           │ 11        │ Ticket, Problem, Change + Followups/Tasks/Validations/Solutions                         │
  │ Assistance       │           │                                                                                         │
  ├──────────────────┼───────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │                  │           │ Computer, Monitor, Printer, Phone, NetworkEquipment, Peripheral,                        │
  │ Assets           │ 18        │ Software+Version+License, Cartridges, Consumables, Certificates, Appliance, Cluster,    │
  │                  │           │ DatabaseInstance, Rack, Enclosure                                                       │
  ├──────────────────┼───────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ Networking       │ 10        │ NetworkPort, IPAddress, IPNetwork, VLAN, FQDN, Domain, DomainRecord, WifiNetwork        │
  ├──────────────────┼───────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ Datacenter       │ 6         │ Datacenter, DCRoom, Cable, CableType, PDU, PassiveDCEquipment                           │
  ├──────────────────┼───────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ Management       │ 9         │ User, Group, Entity (multi-tenant), Location, Supplier, Contact, Contract, Project,     │
  │                  │           │ ProjectTask                                                                             │
  ├──────────────────┼───────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ Docs &           │ 4         │ Document, Budget, Calendar, InfoCom                                                     │
  │ Financials       │           │                                                                                         │
  ├──────────────────┼───────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ Tools            │ 6         │ KnowbaseItem (FAQ), Reminder, SavedSearch, Reservation, ReservationItem, RSSFeed        │
  ├──────────────────┼───────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
  │ Config/Dropdowns │ 20+       │ ITILCategory, State, Profile, SLA, OLA, Manufacturer, ComputerType/Model, RequestType,  │
  │                  │           │ etc.                                                                                    │
  └──────────────────┴───────────┴─────────────────────────────────────────────────────────────────────────────────────────┘

1. Timeline (needs composition)

When you open a ticket in GLPI's web UI, you see a single feed:

10:02  [created] by pedro
10:15  [followup] "asked user for a screenshot"
10:40  [task] assigned to tech-support, 30min estimate
11:05  [status] New → Assigned
11:22  [followup] "reproduced on my side"
11:50  [solution] "restarted the service"
12:00  [status] Assigned → Solved

The REST API does NOT return that feed. It returns each row-type from a separate endpoint: /Ticket/5/TicketFollowup,
/Ticket/5/TicketTask, /Ticket/5/ITILSolution, /Ticket/5/Log (for status/assignment changes). No single call gives you the
merged, sorted chronology.

"Needs composition in MCP" = a tool like glpi_get_ticket_timeline(5) would internally fire 4 GETs in parallel, merge the
results, sort by date_creation, and return one ordered list. This is valuable because the timeline is the #1 artifact a human
(or AI) reads when triaging.

---
2. Massive actions (bulk ops)

In the web UI, you can tick 30 tickets and pick "Close all" from a dropdown. The REST API exposes this via two discovery
endpoints:

- GET /getMassiveActions/Ticket — "what bulk ops are legal on tickets?" → returns ["update", "delete", "add_followup",
"solve", "close", "assign"…]
- GET /getMassiveActionParameters/Ticket/close — "what params does close need?" → returns the field schema

Actual execution is POST /applyMassiveAction/.... The GETs are metadata/capability discovery.

Why it matters: If you ever add write tools, this is the clean way to let AI discover "what can I do to 10 things at once"
instead of hardcoding each bulk op.

---
3. Inventory (GLPI Agent) — async hw/sw discovery

GLPI has a separate data-ingestion pipeline that doesn't touch the REST API:

1. A small daemon (GLPI Agent, formerly FusionInventory) is installed on each workstation/server
2. It wakes every N hours, scans the local machine (CPU, RAM, disks, installed software, MACs, OS)
3. It posts the result to GLPI's inventory endpoint
4. GLPI creates/updates Computer, SoftwareVersion, NetworkPort, etc. records

"Async" = data arrives when the agent runs, not when you query. You can't trigger a scan from MCP. You just read the
resulting records.

"Governed by enabled_inventory" = the global config flag (in $CFG_GLPI, visible via glpi_config) that decides whether GLPI
accepts agent reports. If off, your Computer table goes stale.

Useful MCP angle: "find computers that haven't reported in > 7 days" — flag stale/dead machines. That's a timestamp query on
Computer.last_inventory_update.

---
4. with_* expansion — already implemented, worth understanding

By default GET /Ticket/5 returns only the ticket's own columns. GLPI supports 14 query flags to eagerly join related data in
a single call:

┌──────────────────────────────┬─────────────────────────┐
│             Flag             │          Pulls          │
├──────────────────────────────┼─────────────────────────┤
│ with_documents               │ attached files          │
├──────────────────────────────┼─────────────────────────┤
│ with_logs                    │ change history          │
├──────────────────────────────┼─────────────────────────┤
│ with_notes                   │ private notes           │
├──────────────────────────────┼─────────────────────────┤
│ with_networkports            │ NICs (for assets)       │
├──────────────────────────────┼─────────────────────────┤
│ with_devices                 │ child hardware          │
├──────────────────────────────┼─────────────────────────┤
│ with_softwares               │ installed software      │
├──────────────────────────────┼─────────────────────────┤
│ with_disks                   │ filesystems             │
├──────────────────────────────┼─────────────────────────┤
│ with_connections             │ direct connections      │
├──────────────────────────────┼─────────────────────────┤
│ with_tickets                 │ linked ITIL tickets     │
├──────────────────────────────┼─────────────────────────┤
│ with_problems / with_changes │ linked problems/changes │
├──────────────────────────────┼─────────────────────────┤
│ with_infocoms                │ cost/warranty info      │
├──────────────────────────────┼─────────────────────────┤
│ with_contracts               │ associated contracts    │
├──────────────────────────────┼─────────────────────────┤
│ with_validations             │ approval records        │
└──────────────────────────────┴─────────────────────────┘

Why this matters for tool design: glpi_get_item already exposes all 14 as booleans. So you don't need a new tool — you need
AI to use them. One call with with_documents=true, with_logs=true, with_networkports=true beats three round-trips. Worth
reinforcing in the MCP instructions.

---
5. SLA / OLA — target times + escalation

- SLA (Service Level Agreement) — commitment to the customer. Example: "we answer P1 tickets within 1h, resolve within 4h."
- OLA (Operational Level Agreement) — commitment between internal teams. Example: "Tier-1 hands off to Tier-2 within 30min."

Both are first-class itemtypes (SLA, OLA). Each has:
- Target duration (e.g., 4 hours, respects business calendars)
- Type (time-to-own vs. time-to-resolve)
- Escalation levels (after X% of time, notify manager; at 100%, page oncall)

When a ticket is created under a category that has an SLA attached, GLPI computes due_date and fires escalations
automatically.

MCP value: Queries like "which tickets are at risk of breaching SLA?" (due_date < now + 1h AND status not in [Solved,
Closed]). A glpi_list_sla_ola tool would dump the definitions; a glpi_tickets_at_risk tool would compose a search with the
due-date criteria.

---
6. Multi-entity scoping — this is GLPI's tenancy model

"Entity" = tenant/subsidiary/department. A parent company running GLPI for 5 subsidiaries has 5 entities. Every single record
in GLPI belongs to an entity (Ticket, Computer, User…).

A user can have multiple profiles across multiple entities. Example:
- Pedro is "Technician" in entity PulsoSalud/IT
- Pedro is "Observer" in entity PulsoSalud/HR
- Pedro has no access to entity PulsoSalud/Legal

At session time, Pedro picks one active profile and one or more active entities. Every subsequent API query is implicitly
filtered by those choices. /Ticket?range=0-49 doesn't return all tickets — it returns "all tickets visible under pedro's
current (profile, entity) selection."

Switching is a POST (not currently in the MCP): /changeActiveProfile, /changeActiveEntities. If you ever need "all tickets
across the whole company", you must switch to a profile like Super-Admin with entity = root + recursive.

## Background

### Why connect machines to GLPI?

1. **Asset tracking** — Know exactly what hardware the company owns, who has it, where it is, and its serial number. When someone leaves or a machine breaks, you know what exists and where it went.
2. **Linking assets to tickets** — When a user opens a support ticket ("my computer won't turn on"), the tech can link it to the specific Computer record for context: what model, what software is installed, has it had issues before.

### GLPI Agent

A small program installed on each machine (Windows, Linux, macOS, Android) that runs periodically and reports back to the GLPI server: CPU, RAM, disks, serial number, installed software, network interfaces, OS version, etc. Machines are registered automatically without manual data entry. Formerly known as FusionInventory Agent — GLPI 10 bundled it natively.

### Key config flags

- **`enabled_inventory`** — Whether the built-in inventory module is active. When on, GLPI accepts hardware/software reports from agents on the network.
- **`enable_api`** — Whether the REST API (`/apirest.php`) accepts requests. If off, none of the MCP tools work.
- **`maintenance_mode`** — When on, GLPI blocks normal users and shows a maintenance page. Only super-admins can log in.

# GLPI REST API — Complete GET Endpoints

Verified against `src/Glpi/Api/APIRest.php` (router source code) + `apirest.md` (official docs).
Branch: `11.0/bugfixes` of `glpi-project/glpi`.

Any `:itemtype` is a PHP class inheriting `CommonDBTM`.

---

## A. Session & Config (8 endpoints)

| # | Endpoint | URL | Method |
|---|----------|-----|--------|
| 1 | Init Session | `/initSession` | GET |
| 2 | Kill Session | `/killSession` | GET |
| 3 | Get My Profiles | `/getMyProfiles` | GET |
| 4 | Get Active Profile | `/getActiveProfile` | GET |
| 5 | Get My Entities | `/getMyEntities` | GET |
| 6 | Get Active Entities | `/getActiveEntities` | GET |
| 7 | Get Full Session | `/getFullSession` | GET |
| 8 | Get GLPI Config | `/getGlpiConfig` | GET |

## B. CRUD Read (6 endpoint patterns)

| # | Endpoint | URL Pattern | Method |
|---|----------|-------------|--------|
| 9 | Get an item | `/:itemtype/:id` | GET |
| 10 | Get all items | `/:itemtype/` | GET |
| 11 | Get sub-items | `/:itemtype/:id/:sub_itemtype` | GET |
| 12 | Get multiple items | `/getMultipleItems` | GET |
| 13 | List search options | `/listSearchOptions/:itemtype` | GET |
| 14 | Search items | `/search/:itemtype` | GET |

## C. Massive Actions (2 endpoints)

| # | Endpoint | URL Pattern | Method |
|---|----------|-------------|--------|
| 15 | Get massive actions | `/getMassiveActions/:itemtype[/:id]` | GET |
| 16 | Get massive action params | `/getMassiveActionParameters/:itemtype/:action` | GET |

## D. Special (2 endpoints)

| # | Endpoint | URL Pattern | Method |
|---|----------|-------------|--------|
| 17 | Download document | `/Document/:id` (Accept: application/octet-stream) | GET |
| 18 | User profile picture | `/User/:id/Picture` | GET |

**Total: 18 GET endpoint patterns.**

---

## E. Itemtypes tested in `test_api.py` (22)

| Category | Itemtypes |
|----------|-----------|
| ITIL (3) | Ticket, Problem, Change |
| Assets (7) | Computer, Monitor, NetworkEquipment, Printer, Phone, Peripheral, Software |
| Management (9) | User, Group, Entity, Location, Supplier, Contract, Contact, Document, Budget |
| Config (3) | ITILCategory, Profile, State |

## F. Itemtypes NOT in test script

| Category | Itemtypes |
|----------|-----------|
| ITIL (8) | TicketFollowup, TicketTask, TicketValidation, ITILFollowup, ITILSolution, ProblemTask, ChangeTask, ChangeValidation |
| Assets (11) | CartridgeItem, ConsumableItem, Line, Certificate, Appliance, Cluster, DatabaseInstance, Rack, Enclosure, PDU, PassiveDCEquipment |
| Software (3) | SoftwareVersion, SoftwareLicense, SoftwareCategory |
| Networking (10) | NetworkPort, NetworkName, IPAddress, IPNetwork, VLAN, FQDN, Domain, DomainRecord, DomainRecordType, WifiNetwork |
| Datacenter (4) | Datacenter, DCRoom, Cable, CableType |
| Management (5) | Project, ProjectTask, SLA, OLA, Calendar |
| Tools (6) | Reminder, RSSFeed, KnowbaseItem, SavedSearch, Reservation, ReservationItem |
| Config/Dropdowns (10+) | Manufacturer, ComputerType, ComputerModel, RequestType, SolutionType, TaskCategory, DocumentType, DocumentCategory, ContractType, UserCategory |

## G. Coverage summary

| What | Count | In test_api.py |
|------|-------|----------------|
| GET endpoint patterns | 18 | 4 of 18 (22%) |
| Itemtypes tested | 22 | 22 of ~80+ useful (~27%) |

### Endpoint patterns missing from test

1. getMyProfiles
2. getActiveProfile
3. getMyEntities
4. getActiveEntities
5. getFullSession
6. getGlpiConfig
7. Get single item (`/:itemtype/:id`)
8. Get sub-items (`/:itemtype/:id/:sub_itemtype`)
9. getMultipleItems
10. listSearchOptions
11. getMassiveActions
12. getMassiveActionParameters
13. Document download
14. User profile picture

## H. Useful query parameters

| Parameter | Default | Works on |
|-----------|---------|----------|
| `expand_dropdowns` | false | Get item, Get all, Get sub-items, getMultipleItems |
| `get_hateoas` | true | Get item, Get all, Get sub-items, getMultipleItems |
| `only_id` | false | Get all, Get sub-items |
| `range` | 0-49 | Get all, Get sub-items, Search |
| `sort` | 1 | Get all, Get sub-items, Search |
| `order` | ASC | Get all, Get sub-items, Search |
| `searchText[field]` | NULL | Get all |
| `is_deleted` | false | Get all |
| `with_devices` | — | Get item (Computer, NetworkEquipment, Peripheral, Phone, Printer) |
| `with_disks` | — | Get item (Computer only) |
| `with_softwares` | — | Get item (Computer only) |
| `with_connections` | — | Get item (Computer only) |
| `with_networkports` | — | Get item, Get all |
| `with_infocoms` | — | Get item |
| `with_contracts` | — | Get item |
| `with_documents` | — | Get item |
| `with_tickets` | — | Get item |
| `with_problems` | — | Get item |
| `with_changes` | — | Get item |
| `with_notes` | — | Get item |
| `with_logs` | — | Get item |
| `add_keys_names` | — | Get item, Get all, Get sub-items |
| `get_sha1` | false | Get item, getMultipleItems |
| `raw` | — | listSearchOptions |
| `forcedisplay` | — | Search |
| `criteria` | — | Search |
| `metacriteria` | — | Search (deprecated, use criteria with meta flag) |
| `rawdata` | false | Search |
| `withindexes` | false | Search |
| `uid_cols` | false | Search |
| `giveItems` | false | Search |
