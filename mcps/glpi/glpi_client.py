"""GLPI REST API wrapper with session caching."""

import concurrent.futures
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
import urllib3
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_SESSION_FILE = Path(__file__).parent / ".session.json"

# --- Ticket name → code maps (GLPI 11 standard) ---

TICKET_STATUS = {
    "new": 1, "assigned": 2, "planned": 3, "waiting": 4,
    "pending": 4, "solved": 5, "closed": 6,
}
TICKET_STATUS_LABEL = {v: k.capitalize() for k, v in TICKET_STATUS.items() if k != "pending"}
TICKET_OPEN_STATUSES = [1, 2, 3, 4]  # not solved, not closed

PRIORITY_LEVEL = {
    "very low": 1, "low": 2, "medium": 3, "normal": 3,
    "high": 4, "very high": 5, "major": 6,
}
PRIORITY_LABEL = {1: "Very Low", 2: "Low", 3: "Medium", 4: "High", 5: "Very High", 6: "Major"}

TICKET_TYPE = {"incident": 1, "request": 2}
TICKET_TYPE_LABEL = {1: "Incident", 2: "Request"}

# Common Ticket search-option field IDs (from /listSearchOptions/Ticket in GLPI 11).
# Used as a fast-path; falls back to runtime resolution if a field isn't found here.
TICKET_FIELDS = {
    "name": 1, "title": 1,
    "id": 2,
    "priority": 3,
    "requester": 4, "users_id_recipient": 4,
    "assignee": 5, "assigned_user": 5, "users_id_assign": 5,
    "category": 7, "itilcategories_id": 7,
    "assignee_group": 8, "groups_id_assign": 8,
    "requesttype": 9, "request_source": 9,
    "urgency": 10,
    "impact": 11,
    "status": 12,
    "type": 14,
    "date_creation": 15, "date": 15, "creation_date": 15,
    "due_date": 18, "time_to_resolve": 18, "deadline": 18,
    "date_mod": 19, "modified": 19,
    "content": 21, "description": 21,
    "entity": 80, "entities_id": 80,
}


class GLPIClient:
    """GLPI REST API client with automatic session management."""

    def __init__(self):
        self._api_url = os.getenv("GLPI_API_URL")
        self._app_token = os.getenv("GLPI_APP_TOKEN")
        self._user_token = os.getenv("GLPI_USER_TOKEN")
        if not all([self._api_url, self._app_token, self._user_token]):
            raise RuntimeError(
                "Missing GLPI_API_URL, GLPI_APP_TOKEN, or GLPI_USER_TOKEN in environment"
            )
        self._session_token: str | None = self._load_cached_session()
        self._search_options_cache: dict[str, dict[str, int]] = {}  # itemtype -> {name -> field_id}
        self._user_cache: dict[str, int] = {}
        self._group_cache: dict[str, int] = {}
        self._category_cache: dict[str, int] = {}
        self._entity_cache: dict[str, int] = {}

    # --- Session management ---

    def _load_cached_session(self) -> str | None:
        if _SESSION_FILE.exists():
            try:
                data = json.loads(_SESSION_FILE.read_text())
                return data.get("session_token")
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def _save_session(self, token: str):
        _SESSION_FILE.write_text(json.dumps({"session_token": token}))

    def _init_session(self) -> str:
        resp = requests.get(
            f"{self._api_url}/initSession",
            headers={
                "Authorization": f"user_token {self._user_token}",
                "App-Token": self._app_token,
            },
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        token = resp.json()["session_token"]
        self._session_token = token
        self._save_session(token)
        return token

    def _ensure_session(self) -> str:
        if self._session_token:
            return self._session_token
        return self._init_session()

    def _headers(self) -> dict:
        return {
            "Session-Token": self._ensure_session(),
            "App-Token": self._app_token,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        """GET with auto-retry on 401 (expired session)."""
        resp = requests.get(
            f"{self._api_url}{path}",
            headers=self._headers(),
            params=params,
            timeout=15,
            verify=False,
        )
        if resp.status_code == 401:
            self._session_token = None
            self._init_session()
            resp = requests.get(
                f"{self._api_url}{path}",
                headers=self._headers(),
                params=params,
                timeout=15,
                verify=False,
            )
        return resp

    # --- Session & config endpoints ---
    # NOTE: get_my_profiles, get_active_profile, get_my_entities, and get_active_entities
    # map their respective API endpoints but are unused — get_full_session encompasses all of them.

    def get_my_profiles(self) -> dict:
        resp = self._get("/getMyProfiles")
        resp.raise_for_status()
        return resp.json()

    def get_active_profile(self) -> dict:
        resp = self._get("/getActiveProfile")
        resp.raise_for_status()
        return resp.json()

    def get_my_entities(self) -> dict:
        resp = self._get("/getMyEntities")
        resp.raise_for_status()
        return resp.json()

    def get_active_entities(self) -> dict:
        resp = self._get("/getActiveEntities")
        resp.raise_for_status()
        return resp.json()

    def get_full_session(self) -> dict:
        resp = self._get("/getFullSession")
        resp.raise_for_status()
        return resp.json()

    def get_glpi_config(self) -> dict:
        resp = self._get("/getGlpiConfig")
        resp.raise_for_status()
        return resp.json()

    # --- CRUD read endpoints ---

    def get_item(self, itemtype: str, item_id: int, **kwargs) -> dict:
        params = {}
        for key in (
            "expand_dropdowns", "get_hateoas", "with_devices", "with_disks",
            "with_softwares", "with_connections", "with_networkports",
            "with_infocoms", "with_contracts", "with_documents",
            "with_tickets", "with_problems", "with_changes",
            "with_notes", "with_logs",
        ):
            if key in kwargs and kwargs[key]:
                params[key] = "true"
        resp = self._get(f"/{itemtype}/{item_id}", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_items(
        self,
        itemtype: str,
        range_str: str = "0-49",
        sort: str | None = None,
        order: str = "ASC",
        search_text: dict | None = None,
        is_deleted: bool = False,
        expand_dropdowns: bool = False,
    ) -> list | dict:
        params: dict = {"range": range_str, "order": order}
        if sort:
            params["sort"] = sort
        if is_deleted:
            params["is_deleted"] = "true"
        if expand_dropdowns:
            params["expand_dropdowns"] = "true"
        if search_text:
            for field, value in search_text.items():
                params[f"searchText[{field}]"] = value
        resp = self._get(f"/{itemtype}", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_sub_items(
        self,
        itemtype: str,
        item_id: int,
        sub_itemtype: str,
        range_str: str = "0-49",
    ) -> list | dict:
        params = {"range": range_str}
        resp = self._get(f"/{itemtype}/{item_id}/{sub_itemtype}", params=params)
        resp.raise_for_status()
        return resp.json()

    def list_search_options(self, itemtype: str) -> dict:
        resp = self._get(f"/listSearchOptions/{itemtype}")
        resp.raise_for_status()
        return resp.json()

    def _get_search_options_map(self, itemtype: str) -> dict[str, int]:
        """Return {lowercase_field_name: field_id} for an itemtype, cached."""
        if itemtype not in self._search_options_cache:
            raw = self.list_search_options(itemtype)
            mapping: dict[str, int] = {}
            for key, opt in raw.items():
                if not isinstance(opt, dict) or "name" not in opt:
                    continue
                try:
                    field_id = int(key)
                except ValueError:
                    continue
                mapping[opt["name"].strip().lower()] = field_id
                # Also map the "field" key if present (e.g. "status" -> 12)
                if "field" in opt:
                    mapping[opt["field"].strip().lower()] = field_id
            self._search_options_cache[itemtype] = mapping
        return self._search_options_cache[itemtype]

    def resolve_field(self, itemtype: str, field) -> int:
        """Resolve a field name to its search field ID. Passes through ints unchanged."""
        if isinstance(field, int):
            return field
        # Try parsing as int first (string "12" -> 12)
        try:
            return int(field)
        except (ValueError, TypeError):
            pass
        name_map = self._get_search_options_map(itemtype)
        field_lower = field.strip().lower()
        if field_lower in name_map:
            return name_map[field_lower]
        raise ValueError(
            f"Unknown field '{field}' for {itemtype}. "
            f"Use glpi_list_search_options to see available fields."
        )

    def search_items(
        self,
        itemtype: str,
        criteria: list[dict] | None = None,
        range_str: str = "0-49",
        sort: int | None = None,
        order: str | None = None,
        forcedisplay: list[int] | None = None,
    ) -> dict:
        params: dict = {"range": range_str}
        if sort is not None:
            params["sort"] = sort
        if order:
            params["order"] = order
        if criteria:
            for i, c in enumerate(criteria):
                for key, value in c.items():
                    params[f"criteria[{i}][{key}]"] = value
        if forcedisplay:
            for i, field_id in enumerate(forcedisplay):
                params[f"forcedisplay[{i}]"] = field_id
        resp = self._get(f"/search/{itemtype}", params=params)
        resp.raise_for_status()
        return resp.json()

    # --- Name resolvers (cached) ---

    def _ticket_field(self, name: str) -> int:
        """Fast-path lookup for common Ticket fields, falls back to runtime resolver."""
        key = name.strip().lower()
        if key in TICKET_FIELDS:
            return TICKET_FIELDS[key]
        return self.resolve_field("Ticket", name)

    def _resolve_user(self, identifier) -> int:
        if isinstance(identifier, int):
            return identifier
        try:
            return int(identifier)
        except (ValueError, TypeError):
            pass
        key = identifier.strip()
        if key in self._user_cache:
            return self._user_cache[key]
        # Try login (field 1), realname (field 9), firstname (field 34), email (field 5 on User is often email)
        for field_id in (1, 9, 34):
            result = self.search_items(
                "User",
                criteria=[{"field": field_id, "searchtype": "contains", "value": key}],
                range_str="0-5",
                forcedisplay=[2, 1],
            )
            rows = result.get("data") or []
            if rows:
                user_id = int(rows[0].get("2") or rows[0].get(2))
                self._user_cache[key] = user_id
                return user_id
        raise ValueError(f"No user matching '{identifier}'")

    def _resolve_group(self, identifier) -> int:
        if isinstance(identifier, int):
            return identifier
        try:
            return int(identifier)
        except (ValueError, TypeError):
            pass
        key = identifier.strip()
        if key in self._group_cache:
            return self._group_cache[key]
        result = self.search_items(
            "Group",
            criteria=[{"field": 1, "searchtype": "contains", "value": key}],
            range_str="0-5",
            forcedisplay=[2, 1],
        )
        rows = result.get("data") or []
        if not rows:
            raise ValueError(f"No group matching '{identifier}'")
        gid = int(rows[0].get("2") or rows[0].get(2))
        self._group_cache[key] = gid
        return gid

    def _resolve_category(self, identifier) -> int:
        if isinstance(identifier, int):
            return identifier
        try:
            return int(identifier)
        except (ValueError, TypeError):
            pass
        key = identifier.strip()
        if key in self._category_cache:
            return self._category_cache[key]
        # Try completename first (handles "Parent > Child"), then name
        for field_id in (14, 1):  # 14 is typically completename for tree dropdowns, 1 is name
            result = self.search_items(
                "ITILCategory",
                criteria=[{"field": field_id, "searchtype": "contains", "value": key}],
                range_str="0-5",
                forcedisplay=[2, 1, 14],
            )
            rows = result.get("data") or []
            if rows:
                cid = int(rows[0].get("2") or rows[0].get(2))
                self._category_cache[key] = cid
                return cid
        raise ValueError(f"No ITIL category matching '{identifier}'")

    def _resolve_entity(self, identifier) -> int:
        if isinstance(identifier, int):
            return identifier
        try:
            return int(identifier)
        except (ValueError, TypeError):
            pass
        key = identifier.strip()
        if key in self._entity_cache:
            return self._entity_cache[key]
        result = self.search_items(
            "Entity",
            criteria=[{"field": 1, "searchtype": "contains", "value": key}],
            range_str="0-5",
            forcedisplay=[2, 1],
        )
        rows = result.get("data") or []
        if not rows:
            raise ValueError(f"No entity matching '{identifier}'")
        eid = int(rows[0].get("2") or rows[0].get(2))
        self._entity_cache[key] = eid
        return eid

    # --- Tier 1: Ticket composition tools ---

    def search_tickets(
        self,
        status=None,
        category=None,
        assignee=None,
        requester=None,
        group=None,
        priority=None,
        ticket_type=None,
        entity=None,
        date_from=None,
        date_to=None,
        text=None,
        due_within_hours: int | None = None,
        range_str: str = "0-49",
        sort: int | None = None,
        order: str = "DESC",
    ) -> dict:
        """High-level ticket search with name-based filters. Returns same shape as search_items.

        `due_within_hours`: include only tickets with due_date between epoch and now+N hours
        (captures already-breached + about-to-breach). Combine with status='open' for SLA-risk queries.
        """
        criteria: list[dict] = []

        def add(field, searchtype, value):
            c = {"field": field, "searchtype": searchtype, "value": value}
            if criteria:
                c["link"] = "AND"
            criteria.append(c)

        if status is not None:
            vals = status if isinstance(status, list) else [status]
            codes = []
            for v in vals:
                if isinstance(v, int):
                    codes.append(v)
                elif isinstance(v, str):
                    low = v.strip().lower()
                    if low in TICKET_STATUS:
                        codes.append(TICKET_STATUS[low])
                    elif low == "open":
                        codes.extend(TICKET_OPEN_STATUSES)
                    else:
                        try:
                            codes.append(int(v))
                        except ValueError:
                            raise ValueError(f"Unknown status '{v}'. Use one of: {list(TICKET_STATUS)}")
            # Build OR'd group for multiple statuses
            for i, code in enumerate(codes):
                link = "AND" if (i == 0 and criteria) else ("OR" if i > 0 else None)
                c = {"field": TICKET_FIELDS["status"], "searchtype": "equals", "value": code}
                if link:
                    c["link"] = link
                criteria.append(c)

        if priority is not None:
            code = priority if isinstance(priority, int) else PRIORITY_LEVEL.get(priority.strip().lower())
            if code is None:
                raise ValueError(f"Unknown priority '{priority}'. Use one of: {list(PRIORITY_LEVEL)}")
            add(TICKET_FIELDS["priority"], "equals", code)

        if ticket_type is not None:
            code = ticket_type if isinstance(ticket_type, int) else TICKET_TYPE.get(ticket_type.strip().lower())
            if code is None:
                raise ValueError(f"Unknown type '{ticket_type}'. Use one of: {list(TICKET_TYPE)}")
            add(TICKET_FIELDS["type"], "equals", code)

        if category is not None:
            add(TICKET_FIELDS["category"], "equals", self._resolve_category(category))

        if assignee is not None:
            add(TICKET_FIELDS["assignee"], "equals", self._resolve_user(assignee))

        if requester is not None:
            add(TICKET_FIELDS["requester"], "equals", self._resolve_user(requester))

        if group is not None:
            add(TICKET_FIELDS["assignee_group"], "equals", self._resolve_group(group))

        if entity is not None:
            add(TICKET_FIELDS["entity"], "equals", self._resolve_entity(entity))

        if date_from is not None:
            add(TICKET_FIELDS["date_creation"], "morethan", date_from)

        if date_to is not None:
            add(TICKET_FIELDS["date_creation"], "lessthan", date_to)

        if text is not None:
            add(TICKET_FIELDS["name"], "contains", text)

        if due_within_hours is not None:
            horizon = (datetime.now() + timedelta(hours=due_within_hours)).strftime("%Y-%m-%d %H:%M:%S")
            add(TICKET_FIELDS["due_date"], "lessthan", horizon)
            add(TICKET_FIELDS["due_date"], "morethan", "1970-01-01 00:00:00")

        return self.search_items(
            "Ticket",
            criteria=criteria or None,
            range_str=range_str,
            sort=sort if sort is not None else TICKET_FIELDS["date_creation"],
            order=order,
            forcedisplay=[2, 1, 7, 12, 3, 14, 15, 19, 4, 5],
        )

    _TIMELINE_SUBS = {
        "Ticket": [
            ("followup", "TicketFollowup"),
            ("task", "TicketTask"),
            ("solution", "ITILSolution"),
            ("validation", "TicketValidation"),
            ("log", "Log"),
        ],
        "Problem": [
            ("followup", "ITILFollowup"),
            ("task", "ProblemTask"),
            ("solution", "ITILSolution"),
            ("log", "Log"),
        ],
        "Change": [
            ("followup", "ITILFollowup"),
            ("task", "ChangeTask"),
            ("solution", "ITILSolution"),
            ("validation", "ChangeValidation"),
            ("log", "Log"),
        ],
    }

    def get_itil_timeline(self, itemtype: str, item_id: int) -> list[dict]:
        """Merge followups, tasks, solutions, validations, and logs into a sorted chronological feed."""
        subs = self._TIMELINE_SUBS.get(itemtype)
        if subs is None:
            raise ValueError(f"Timeline only supported for Ticket, Problem, Change (got {itemtype})")

        def fetch(kind_and_type):
            kind, sub_type = kind_and_type
            try:
                items = self.get_sub_items(itemtype, item_id, sub_type, range_str="0-500")
                if isinstance(items, list):
                    return [{**row, "_kind": kind, "_sub_type": sub_type} for row in items]
                return []
            except requests.HTTPError as e:
                return [{"_kind": kind, "_sub_type": sub_type, "_error": str(e)}]

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(subs)) as ex:
            batches = list(ex.map(fetch, subs))

        merged = [row for batch in batches for row in batch]

        def keyfn(row):
            return (
                row.get("date_creation")
                or row.get("date")
                or row.get("date_mod")
                or ""
            )

        merged.sort(key=keyfn)
        return merged

    def get_ticket_full(self, ticket_id: int) -> dict:
        """Fetch a ticket with expanded relations, followups, tasks, solutions, validations, linked users/groups/docs/assets, and a sorted chronological timeline of all events.

        Timeline combines followups + tasks + solutions + validations + log rows, each tagged with `_kind`.
        All network calls run in parallel.
        """
        def fetch_item():
            return self.get_item(
                "Ticket", ticket_id,
                expand_dropdowns=True,
                with_documents=True, with_logs=True, with_notes=True,
                with_problems=True, with_changes=True, with_contracts=True,
                with_infocoms=True,
            )

        def fetch_sub(sub_type):
            try:
                return self.get_sub_items("Ticket", ticket_id, sub_type, range_str="0-500")
            except requests.HTTPError:
                return None

        subs = [
            "TicketFollowup", "TicketTask", "ITILSolution", "TicketValidation",
            "Log",
            "Ticket_User", "Group_Ticket", "Document_Item", "Item_Ticket",
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(subs) + 1) as ex:
            future_item = ex.submit(fetch_item)
            future_subs = {s: ex.submit(fetch_sub, s) for s in subs}
            item = future_item.result()
            sub_results = {s: f.result() for s, f in future_subs.items()}

        # Compose timeline from the already-fetched event subs
        timeline: list[dict] = []
        for kind, sub in (
            ("followup", "TicketFollowup"),
            ("task", "TicketTask"),
            ("solution", "ITILSolution"),
            ("validation", "TicketValidation"),
            ("log", "Log"),
        ):
            rows = sub_results.get(sub) or []
            if isinstance(rows, list):
                timeline.extend({**row, "_kind": kind, "_sub_type": sub} for row in rows)

        def _timeline_key(row):
            return row.get("date_creation") or row.get("date") or row.get("date_mod") or ""

        timeline.sort(key=_timeline_key)

        return {
            "ticket": item,
            "timeline": timeline,
            "followups": sub_results.get("TicketFollowup") or [],
            "tasks": sub_results.get("TicketTask") or [],
            "solutions": sub_results.get("ITILSolution") or [],
            "validations": sub_results.get("TicketValidation") or [],
            "linked_users": sub_results.get("Ticket_User") or [],
            "linked_groups": sub_results.get("Group_Ticket") or [],
            "linked_documents": sub_results.get("Document_Item") or [],
            "linked_items": sub_results.get("Item_Ticket") or [],
        }

    def get_ticket_stats(
        self,
        group_by: str = "status",
        date_from: str | None = None,
        date_to: str | None = None,
        status=None,
        category=None,
        assignee=None,
        entity=None,
    ) -> dict:
        """Count tickets grouped by status/category/priority/assignee/type. Returns {label: count, _total: N}."""
        group_by_key = group_by.strip().lower()
        field_id = TICKET_FIELDS.get(group_by_key)
        if field_id is None:
            raise ValueError(
                f"group_by must be one of: status, category, priority, assignee, type, "
                f"requester, entity, assignee_group (got {group_by!r})"
            )

        result = self.search_tickets(
            status=status, category=category, assignee=assignee, entity=entity,
            date_from=date_from, date_to=date_to,
            range_str="0-5000",
        )

        counts: dict = {}
        for row in result.get("data") or []:
            raw = row.get(str(field_id)) or row.get(field_id)
            if raw is None or raw == "":
                label = "(none)"
            else:
                label = str(raw)
                # Humanize known numeric codes
                if group_by_key == "status":
                    try:
                        label = TICKET_STATUS_LABEL.get(int(raw), label)
                    except (ValueError, TypeError):
                        pass
                elif group_by_key == "priority":
                    try:
                        label = PRIORITY_LABEL.get(int(raw), label)
                    except (ValueError, TypeError):
                        pass
                elif group_by_key == "type":
                    try:
                        label = TICKET_TYPE_LABEL.get(int(raw), label)
                    except (ValueError, TypeError):
                        pass
            counts[label] = counts.get(label, 0) + 1

        sorted_counts = dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))
        sorted_counts["_total"] = result.get("totalcount", sum(counts.values()))
        sorted_counts["_group_by"] = group_by_key
        return sorted_counts

    # --- Tier 2: Enrichment tools ---

    def list_categories(self, with_counts: bool = False) -> list[dict]:
        """ITIL category tree with completename (hierarchy path). Optionally include ticket counts per leaf."""
        raw = self.get_items(
            "ITILCategory", range_str="0-1000",
            sort="completename", order="ASC", expand_dropdowns=True,
        )
        if not isinstance(raw, list):
            return []
        result = []
        for c in raw:
            entry = {
                "id": c.get("id"),
                "name": c.get("name"),
                "completename": c.get("completename") or c.get("name"),
                "parent_id": c.get("itilcategories_id") or 0,
                "level": c.get("level"),
                "comment": c.get("comment"),
            }
            if with_counts:
                try:
                    s = self.search_items(
                        "Ticket",
                        criteria=[{"field": TICKET_FIELDS["category"], "searchtype": "equals", "value": entry["id"]}],
                        range_str="0-0",
                        forcedisplay=[2],
                    )
                    entry["ticket_count"] = s.get("totalcount", 0)
                except Exception:
                    entry["ticket_count"] = None
            result.append(entry)
        return result

    def list_sla_ola(self) -> dict:
        """Return SLA and OLA definitions with target times and attached categories."""
        def fetch(itemtype):
            try:
                r = self.get_items(itemtype, range_str="0-200", expand_dropdowns=True)
                return r if isinstance(r, list) else []
            except requests.HTTPError:
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            sla_fut = ex.submit(fetch, "SLA")
            ola_fut = ex.submit(fetch, "OLA")
            slas = sla_fut.result()
            olas = ola_fut.result()
        return {"SLA": slas, "OLA": olas}

    def search_knowbase(self, query: str, range_str: str = "0-20") -> dict:
        """Search knowledge base articles by title and content. Field IDs resolved dynamically per GLPI version."""
        opts = self._get_search_options_map("KnowbaseItem")
        name_field = opts.get("name") or opts.get("tema") or opts.get("subject") or opts.get("title")
        answer_field = opts.get("answer") or opts.get("contenido") or opts.get("content")
        id_field = opts.get("id") or 2

        if name_field is None:
            raise RuntimeError("Could not locate KnowbaseItem 'name' field in listSearchOptions")

        criteria = [{"field": name_field, "searchtype": "contains", "value": query}]
        if answer_field is not None:
            criteria.append({
                "field": answer_field, "searchtype": "contains", "value": query, "link": "OR",
            })

        forcedisplay = [id_field, name_field]
        if answer_field is not None:
            forcedisplay.append(answer_field)

        return self.search_items(
            "KnowbaseItem",
            criteria=criteria,
            range_str=range_str,
            forcedisplay=forcedisplay,
        )

    def download_document(self, document_id: int) -> tuple[bytes, str, str]:
        """Download a document's raw bytes. Returns (data, filename, mime). Raises if GLPI returns its HTML error page."""
        meta = self.get_item("Document", document_id)
        filename = meta.get("filename") or f"document_{document_id}.bin"
        mime = meta.get("mime") or "application/octet-stream"

        headers = {
            "Session-Token": self._ensure_session(),
            "App-Token": self._app_token,
            "Accept": "application/octet-stream",
        }
        resp = requests.get(
            f"{self._api_url}/Document/{document_id}",
            headers=headers, timeout=30, verify=False,
        )
        if resp.status_code == 401:
            self._session_token = None
            headers["Session-Token"] = self._init_session()
            resp = requests.get(
                f"{self._api_url}/Document/{document_id}",
                headers=headers, timeout=30, verify=False,
            )
        resp.raise_for_status()

        # GLPI replies 200 + text/html when the underlying file is missing on disk. Detect and raise.
        ct = (resp.headers.get("Content-Type") or "").lower()
        if ct.startswith("text/html") or resp.content.startswith(b"Error "):
            body = resp.text[:200]
            raise RuntimeError(f"Document {document_id} not downloadable ({filename}): {body}")

        return resp.content, filename, mime

    def get_user_context(self, identifier) -> dict:
        """Resolve a user and return their profile, groups, entity, and recent tickets (opened & assigned)."""
        user_id = self._resolve_user(identifier)

        def fetch_user():
            return self.get_item("User", user_id, expand_dropdowns=True)

        def fetch_groups():
            try:
                return self.get_sub_items("User", user_id, "Group_User", range_str="0-50")
            except requests.HTTPError:
                return []

        def fetch_opened():
            try:
                return self.search_tickets(requester=user_id, range_str="0-20")
            except Exception as e:
                return {"_error": str(e)}

        def fetch_assigned():
            try:
                return self.search_tickets(assignee=user_id, range_str="0-20")
            except Exception as e:
                return {"_error": str(e)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            f_user = ex.submit(fetch_user)
            f_groups = ex.submit(fetch_groups)
            f_opened = ex.submit(fetch_opened)
            f_assigned = ex.submit(fetch_assigned)
            user = f_user.result()
            groups = f_groups.result()
            opened = f_opened.result()
            assigned = f_assigned.result()

        return {
            "user": user,
            "groups": groups,
            "tickets_opened": opened,
            "tickets_assigned": assigned,
        }

    def kill_session(self):
        try:
            self._get("/killSession")
        finally:
            self._session_token = None
            if _SESSION_FILE.exists():
                _SESSION_FILE.unlink()
