"""GLPI MCP Server — IT service management via GLPI REST API."""

import json
import os

from fastmcp import FastMCP
from fastmcp.utilities.types import File

from glpi_client import GLPIClient

mcp = FastMCP(
    "GLPI",
    instructions="""IMPORTANT: Always discover a tool's schema with ToolSearch BEFORE calling it for the first time.

This server connects to a GLPI instance (IT service management) at ti.pulsosalud.com.

Ticket status codes and emojis (use the emoji when presenting status to the user):
  1=New       🆕
  2=Assigned  👤
  3=Planned   📅
  4=Waiting   ⏸️
  5=Solved    ✅
  6=Closed    🔒

When presenting ticket lists:
- Start each row with the time (HH:MM), then "[<emoji>] — <Status>", then " — ", then #id, title, category
- No numbered list; one ticket per line, in the order returned by the tool (tools default to chronological ascending — oldest first)
- Use expand_dropdowns=true when showing data to users (names instead of IDs)
- For search results, field IDs map to: 1=name, 2=id, 7=category, 12=status, 15=date_creation

Example row:
  06:56 [🆕] — Status — #32654 ELIMINAR ATENCION · ANA Prevention
""",
)

_client: GLPIClient | None = None


def _get_client() -> GLPIClient:
    global _client
    if _client is None:
        _client = GLPIClient()
    return _client


def _json(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


# --- Server info ---


_CONFIG_KEYS = [
    "version", "url_base", "admin_email", "admin_reply", "smtp_sender",
    "language", "timezone", "planning_begin", "planning_end", "time_step",
    "list_limit", "list_limit_max", "enabled_inventory", "enable_api",
    "maintenance_mode", "priority_matrix", "password_min_length",
    "password_need_number", "password_need_letter", "password_need_caps",
    "password_need_symbol", "ticket_types", "asset_types", "inventory_frequency",
]


@mcp.tool()
def glpi_server_info(include_config: bool = True) -> str:
    """Get the server's identity in one call.

    - session: active profile and permissions, all profiles, entities, user info, UI preferences.
      (Encompasses getMyProfiles, getActiveProfile, getMyEntities, getActiveEntities.)
    - config (when include_config=True): curated $CFG_GLPI subset — version, URL, emails, timezone,
      list limits, API/maintenance flags, password policy, ticket/asset type lists.

    Args:
        include_config: Include the curated GLPI config subset (default: True).
    """
    client = _get_client()
    result: dict = {"session": client.get_full_session()}
    if include_config:
        raw = client.get_glpi_config()
        cfg = raw.get("cfg_glpi", raw)
        result["config"] = {k: cfg[k] for k in _CONFIG_KEYS if k in cfg}
    return _json(result)


# --- CRUD read ---


@mcp.tool()
def glpi_list_search_options(itemtype: str) -> str:
    """List all searchable fields for an itemtype. Use before glpi_search to know which field IDs to use.

    Args:
        itemtype: GLPI class name (e.g. "Ticket", "Computer").
    """
    return _json(_get_client().list_search_options(itemtype))


@mcp.tool()
def glpi_search(
    itemtype: str,
    criteria: str = "[]",
    range: str = "0-49",
    sort: int | None = None,
    order: str | None = None,
    forcedisplay: str = "[]",
) -> str:
    """Advanced search with criteria. Use glpi_list_search_options first to find field IDs.

    Args:
        itemtype: GLPI class name (e.g. "Ticket", "Computer").
        criteria: JSON array of criteria objects. Each has: field (int), searchtype (str), value (str), and optionally link ("AND"/"OR").
            Search types: "contains", "equals", "notequals", "lessthan", "morethan", "under", "notunder".
            Example: [{"field": 12, "searchtype": "equals", "value": 1}] — tickets with status New.
        range: Pagination range (default "0-49").
        sort: Field ID to sort by.
        order: "ASC" or "DESC".
        forcedisplay: JSON array of field IDs to include in results. Example: [1, 2, 12, 15].
    """
    import json as _json_mod
    parsed_criteria = _json_mod.loads(criteria) if isinstance(criteria, str) else criteria
    parsed_display = _json_mod.loads(forcedisplay) if isinstance(forcedisplay, str) else forcedisplay
    return _json(_get_client().search_items(
        itemtype,
        criteria=parsed_criteria or None,
        range_str=range,
        sort=sort,
        order=order,
        forcedisplay=parsed_display or None,
    ))


# --- Tier 1: Ticket composition tools ---


@mcp.tool()
def glpi_search_tickets(
    status: str | None = None,
    category: str | None = None,
    assignee: str | None = None,
    requester: str | None = None,
    group: str | None = None,
    priority: str | None = None,
    ticket_type: str | None = None,
    entity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    text: str | None = None,
    due_within_hours: int | None = None,
    range: str = "0-49",
) -> str:
    """Search tickets with name-based filters. Resolves names to IDs internally.

    Results are always sorted by creation date ASC (oldest first — chronological reading order).

    For "tickets opened today": pass date_from="YYYY-MM-DD 00:00:00".
    For "tickets at risk of breaching SLA": combine due_within_hours=24 with status="open".

    Args:
        status: "new", "assigned", "planned", "waiting", "solved", "closed", or "open" (= not solved/closed).
        category: ITIL category name or "Parent > Child" path.
        assignee: User login, realname, firstname, email, or numeric ID — of the technician assigned.
        requester: User login/name of the person who opened the ticket.
        group: Assignee group name.
        priority: "very low", "low", "medium", "high", "very high", "major".
        ticket_type: "incident" or "request".
        entity: Entity name.
        date_from: ISO datetime "YYYY-MM-DD HH:MM:SS" — tickets created after.
        date_to: ISO datetime — tickets created before.
        text: Substring to match in ticket name/title.
        due_within_hours: Include only tickets with a due_date within N hours from now
            (captures already-breached + about-to-breach). Combine with status='open' for SLA-risk queries.
        range: Pagination (default "0-49").
    """
    return _json(_get_client().search_tickets(
        status=status, category=category, assignee=assignee, requester=requester,
        group=group, priority=priority, ticket_type=ticket_type, entity=entity,
        date_from=date_from, date_to=date_to, text=text,
        due_within_hours=due_within_hours,
        range_str=range,
    ))


@mcp.tool()
def glpi_get_itil_timeline(itemtype: str, item_id: int) -> str:
    """Chronological feed for a Ticket/Problem/Change: merges followups + tasks + solutions + validations + logs, sorted by date.

    Each entry is annotated with `_kind` (followup/task/solution/validation/log) and `_sub_type` (the source endpoint).

    Args:
        itemtype: "Ticket", "Problem", or "Change".
        item_id: The ID of the item.
    """
    return _json(_get_client().get_itil_timeline(itemtype, item_id))


@mcp.tool()
def glpi_get_ticket_full(ticket_id: int) -> str:
    """Fetch a ticket with every useful relation in one call: expanded fields, documents, logs, notes, linked problems/changes/contracts, plus followups, tasks, solutions, validations, linked users/groups/assets, AND a sorted chronological `timeline` combining followups + tasks + solutions + validations + logs.

    Use this instead of making 6+ separate calls to understand a ticket end-to-end. The timeline field replaces the need to also call glpi_get_itil_timeline for tickets.
    """
    return _json(_get_client().get_ticket_full(ticket_id))


# --- Tier 2: Enrichment tools ---


@mcp.tool()
def glpi_list_reference(with_counts: bool = False) -> str:
    """ITIL reference data in one call: category tree + SLA + OLA definitions.

    - categories: full category tree with 'completename' (Parent > Child paths).
    - sla: customer-facing agreements (can be empty if the instance doesn't use SLAs).
    - ola: internal agreements. Each has humanized `type` (TTR/TTO) and an `attached_categories`
      list showing which ITIL categories route tickets to it.

    One ITILCategory fetch is shared between the category listing and the SLA/OLA reverse-join,
    so this costs 3 HTTP calls total (SLA + OLA + ITILCategory in parallel).

    Args:
        with_counts: If true, include per-category ticket count (one extra search per category — slow).
    """
    return _json(_get_client().list_reference(with_counts=with_counts))


@mcp.tool()
def glpi_search_knowbase(query: str, range: str = "0-20") -> str:
    """Search GLPI's knowledge base (FAQ) by title and content. Use before triaging a ticket to find prior solutions.

    Args:
        query: Search text.
        range: Pagination (default "0-20").
    """
    return _json(_get_client().search_knowbase(query, range_str=range))


@mcp.tool()
def glpi_download_document(document_id: int) -> File:
    """Download a document's bytes. Returns a File suitable for inline inspection.

    Raises if GLPI's underlying file is missing on disk (common on legacy servers).
    """
    data, filename, mime = _get_client().download_document(document_id)
    ext = os.path.splitext(filename)[1].lstrip(".").lower() or "bin"
    return File(data=data, format=ext, name=filename)


@mcp.tool()
def glpi_get_user_context(identifier: str) -> str:
    """Resolve a user (by login, realname, firstname, email, or numeric ID) and return their profile, group memberships, tickets they opened, and tickets assigned to them.

    Use when you need to understand "who is X and what's on their plate."

    Args:
        identifier: Login name, realname, firstname, email, or numeric user ID.
    """
    return _json(_get_client().get_user_context(identifier))
