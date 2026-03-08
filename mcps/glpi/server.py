"""GLPI MCP Server — IT service management via GLPI REST API."""

import json

from fastmcp import FastMCP

from glpi_client import GLPIClient

mcp = FastMCP(
    "GLPI",
    instructions="""IMPORTANT: Always discover a tool's schema with ToolSearch BEFORE calling it for the first time.

This server connects to a GLPI instance (IT service management) at ti.pulsosalud.com.

Ticket status codes: 1=New, 2=Assigned, 3=Planned, 4=Waiting, 5=Solved, 6=Closed.

When presenting results:
- Format ticket lists as numbered items with status, title, and date
- Use expand_dropdowns=true when showing data to users (names instead of IDs)
- For search results, field IDs map to: 1=name, 2=id, 7=category, 12=status, 15=date_creation
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


# --- Session & config ---


@mcp.tool()
def glpi_get_session() -> str:
    """Get full session data: active profile and permissions, all profiles, entities, user info, and UI preferences.

    Encompasses getMyProfiles, getActiveProfile, getMyEntities, and getActiveEntities in a single call.
    """
    return _json(_get_client().get_full_session())


_CONFIG_KEYS = [
    "version", "url_base", "admin_email", "admin_reply", "smtp_sender",
    "language", "timezone", "planning_begin", "planning_end", "time_step",
    "list_limit", "list_limit_max", "enabled_inventory", "enable_api",
    "maintenance_mode", "priority_matrix", "password_min_length",
    "password_need_number", "password_need_letter", "password_need_caps",
    "password_need_symbol", "ticket_types", "asset_types", "inventory_frequency",
]


@mcp.tool()
def glpi_config(full: bool = False) -> str:
    """Get global GLPI configuration ($CFG_GLPI).

    By default returns only the important keys (version, emails, timezone, limits, etc.).

    Args:
        full: Return the entire $CFG_GLPI dump instead of the curated subset.
    """
    data = _get_client().get_glpi_config()
    if full:
        return _json(data)
    cfg = data.get("cfg_glpi", data)
    return _json({k: cfg[k] for k in _CONFIG_KEYS if k in cfg})


# --- CRUD read ---


@mcp.tool()
def glpi_get_item(
    itemtype: str,
    item_id: int,
    expand_dropdowns: bool = False,
    with_tickets: bool = False,
    with_documents: bool = False,
    with_logs: bool = False,
    with_notes: bool = False,
    with_networkports: bool = False,
    with_contracts: bool = False,
    with_problems: bool = False,
    with_changes: bool = False,
    with_infocoms: bool = False,
    with_devices: bool = False,
    with_softwares: bool = False,
    with_connections: bool = False,
    with_disks: bool = False,
) -> str:
    """Get a single item by ID. Works with any itemtype (Ticket, Computer, User, etc.).

    Args:
        itemtype: GLPI class name (e.g. "Ticket", "Computer", "User", "Software").
        item_id: Unique ID of the item.
        expand_dropdowns: Show names instead of IDs for dropdown fields.
        with_tickets: Include associated ITIL tickets.
        with_documents: Include attached documents.
        with_logs: Include change history.
        with_notes: Include notes.
        with_networkports: Include network connections.
        with_contracts: Include associated contracts.
        with_problems: Include associated ITIL problems.
        with_changes: Include associated ITIL changes.
        with_infocoms: Include financial/administrative info.
        with_devices: Include hardware components (Computer, NetworkEquipment, Peripheral, Phone, Printer).
        with_softwares: Include installed software (Computer only).
        with_connections: Include direct connections (Computer only).
        with_disks: Include file systems (Computer only).
    """
    return _json(_get_client().get_item(
        itemtype, item_id,
        expand_dropdowns=expand_dropdowns,
        with_tickets=with_tickets,
        with_documents=with_documents,
        with_logs=with_logs,
        with_notes=with_notes,
        with_networkports=with_networkports,
        with_contracts=with_contracts,
        with_problems=with_problems,
        with_changes=with_changes,
        with_infocoms=with_infocoms,
        with_devices=with_devices,
        with_softwares=with_softwares,
        with_connections=with_connections,
        with_disks=with_disks,
    ))


@mcp.tool()
def glpi_get_items(
    itemtype: str,
    range: str = "0-49",
    sort: int = 1,
    order: str = "ASC",
    is_deleted: bool = False,
    expand_dropdowns: bool = False,
) -> str:
    """List items of a given type (paginated).

    Args:
        itemtype: GLPI class name (e.g. "Ticket", "Computer", "User").
        range: Pagination range as "start-end" (default "0-49").
        sort: Field ID to sort by (default 1 = name).
        order: "ASC" or "DESC".
        is_deleted: Return items in the trashbin.
        expand_dropdowns: Show names instead of IDs.
    """
    return _json(_get_client().get_items(
        itemtype, range_str=range, sort=sort, order=order,
        is_deleted=is_deleted, expand_dropdowns=expand_dropdowns,
    ))


@mcp.tool()
def glpi_get_sub_items(
    itemtype: str,
    item_id: int,
    sub_itemtype: str,
    range: str = "0-49",
) -> str:
    """Get related sub-items of an item. E.g. Ticket/5/TicketFollowup, Computer/3/NetworkPort.

    Args:
        itemtype: Parent item type (e.g. "Ticket").
        item_id: Parent item ID.
        sub_itemtype: Related item type (e.g. "TicketFollowup", "TicketTask", "Log").
        range: Pagination range as "start-end" (default "0-49").
    """
    return _json(_get_client().get_sub_items(itemtype, item_id, sub_itemtype, range_str=range))


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


@mcp.tool()
def glpi_tickets_today() -> str:
    """Get all tickets created today. Returns id, name, category, status, and creation date."""
    return _json(_get_client().search_tickets_today())
