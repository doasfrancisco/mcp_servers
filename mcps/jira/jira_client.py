"""Jira Cloud client — read-only wrapper around atlassian-python-api.

Gotchas worth knowing:

- Jira Cloud JQL needs a bounded query. A plain `ORDER BY created DESC` with no
  WHERE clause is rejected with "Aquí no se permiten las consultas JQL
  ilimitadas" / "Unbounded JQL queries are not allowed here." Every search must
  include at least one filter clause (project = X, created >= -30d,
  assignee = currentUser(), status = "Open", etc.). The server instructions
  and tool docstring repeat this, but enforce it at the call site too if the
  query starts with ORDER BY — see `search_issues` below.

- `cloud=True` is required when talking to *.atlassian.net. The API token goes
  in `password`, NOT in the `token` parameter (that one is for Data Center PATs).

- The library exposes two naming conventions: `issue_get_*` (newer) and
  `get_issue_*` (older). Both are on the class; we use whichever exists.
"""

import os
from pathlib import Path
from typing import Any, Optional

from atlassian import Jira
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

_URL = os.getenv("JIRA_URL")
_EMAIL = os.getenv("JIRA_EMAIL")
_TOKEN = os.getenv("JIRA_API_TOKEN")

if not (_URL and _EMAIL and _TOKEN):
    raise RuntimeError("Missing JIRA_URL / JIRA_EMAIL / JIRA_API_TOKEN in .env")

# Cloud=True is mandatory for *.atlassian.net. Token goes in `password`.
_jira = Jira(url=_URL, username=_EMAIL, password=_TOKEN, cloud=True)


# ---------- helpers ----------

def slim_issue(iss: dict) -> dict:
    """Flatten a Jira issue payload down to fields that matter for AI clients."""
    f = iss.get("fields", {}) or {}
    status = f.get("status") or {}
    priority = f.get("priority") or {}
    issuetype = f.get("issuetype") or {}
    assignee = f.get("assignee") or {}
    reporter = f.get("reporter") or {}
    parent = f.get("parent") or {}
    return {
        "key": iss.get("key"),
        "id": iss.get("id"),
        "summary": f.get("summary"),
        "status": status.get("name"),
        "status_category": (status.get("statusCategory") or {}).get("key"),
        "priority": priority.get("name"),
        "issuetype": issuetype.get("name"),
        "assignee": assignee.get("displayName"),
        "assignee_account_id": assignee.get("accountId"),
        "reporter": reporter.get("displayName"),
        "created": f.get("created"),
        "updated": f.get("updated"),
        "resolution": (f.get("resolution") or {}).get("name"),
        "labels": f.get("labels"),
        "parent": parent.get("key") if parent else None,
        "project": (f.get("project") or {}).get("key"),
        "description": f.get("description"),
    }


# ---------- issues ----------

def search_issues(
    jql: str,
    fields: str = "summary,status,priority,issuetype,assignee,reporter,created,updated,resolution,labels,project,parent",
    expand: Optional[str] = None,
    slim: bool = True,
) -> dict:
    # Fail fast on unbounded queries — Jira Cloud rejects them with a 400
    # wrapped in a cryptic Spanish error.
    stripped = jql.strip().lower()
    if not stripped or stripped.startswith("order by"):
        raise ValueError(
            "Jira Cloud rejects unbounded JQL. Add at least one filter clause "
            "(e.g. project = X, created >= -30d, assignee = currentUser()) "
            "before any ORDER BY."
        )

    # Use enhanced_jql (Cloud-native /rest/api/3/search/jql). Cloud's old
    # /rest/api/2/search dropped total/startAt/maxResults, so we page with
    # nextPageToken instead. Loop until isLast to return every match.
    all_issues: list = []
    next_token: Optional[str] = None
    while True:
        result = _jira.enhanced_jql(
            jql,
            fields=fields,
            nextPageToken=next_token,
            limit=100,
            expand=expand,
        ) or {}
        page = result.get("issues", []) or []
        all_issues.extend(page)
        if result.get("isLast"):
            break
        next_token = result.get("nextPageToken")
        if not next_token:
            break
    return {
        "count": len(all_issues),
        "issues": [slim_issue(i) for i in all_issues] if slim else all_issues,
    }


def get_issue_full(key: str) -> dict:
    """One-shot: base issue + changelog + status history + comments + worklog +
    watchers + attachments list + available transitions. Saves the AI from
    making 5+ round-trips to understand a single ticket."""
    return {
        "issue": _jira.issue(key, fields="*all", expand="renderedFields,names,schema"),
        "changelog": _jira.get_issue_changelog(key),
        "status_changelog": _jira.get_issue_status_changelog(key),
        "comments": _jira.issue_get_comments(key),
        "worklog": _jira.issue_get_worklog(key),
        "watchers": _jira.issue_get_watchers(key),
        "attachments": _jira.get_attachments_ids_from_issue(key),
        "transitions": _jira.get_issue_transitions(key),
    }


def get_attachment(attachment_id: str) -> Any:
    return _jira.get_attachment(attachment_id)


def download_attachments(attachment_ids: list[str]) -> dict:
    """Fetch one or more attachments and save each to ~/Downloads under its
    original filename. One bad ID doesn't abort the batch — the failing entry
    gets an `error` field and the rest proceed. Returns {count, downloads}."""
    target_dir = Path.home() / "Downloads"
    target_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for aid in attachment_ids:
        try:
            meta = _jira.get_attachment(aid) or {}
            filename = meta.get("filename") or f"jira_attachment_{aid}.bin"
            mime = meta.get("mimeType")
            content = _jira.get_attachment_content(aid)
            data = content if isinstance(content, (bytes, bytearray)) else str(content).encode("latin-1")
            path = target_dir / filename
            path.write_bytes(data)
            results.append({
                "attachment_id": aid,
                "path": str(path),
                "filename": filename,
                "size": len(data),
                "mime": mime,
            })
        except Exception as e:
            results.append({"attachment_id": aid, "error": f"{type(e).__name__}: {e}"})
    return {"count": len(results), "downloads": results}


# ---------- projects ----------

def list_projects(expand: Optional[str] = None) -> Any:
    return _jira.projects(expand=expand)


def get_project_full(key: str) -> dict:
    """One-shot: project metadata + components + versions + approximate issue count.

    Note on issue count: the library's `get_project_issues_count()` assumes the
    old Cloud search response had a `total` field. Jira Cloud moved to
    token-based paging and dropped `total`, so that method now KeyErrors. We use
    `approximate_issue_count()` instead — it's the Cloud-native fast count
    endpoint and returns an approximate integer.
    """
    return {
        "project": _jira.project(key),
        "components": _jira.get_project_components(key),
        "versions": _jira.get_project_versions(key),
        "issue_count": _jira.approximate_issue_count(f'project = "{key}"'),
    }


# ---------- users ----------

def search_users(query: str) -> dict:
    results: list = []
    start = 0
    page = 50
    while True:
        batch = _jira.user_find_by_user_string(query=query, start=start, limit=page) or []
        results.extend(batch)
        if len(batch) < page:
            break
        start += page
    return {"count": len(results), "users": results}


def get_myself() -> Any:
    # The library's myself() hits /rest/api/2/myself without ?expand, so the
    # response has groups.size / applicationRoles.size but empty items arrays.
    # We hit the endpoint directly with expand to include group + role names.
    return _jira.get("rest/api/2/myself?expand=groups,applicationRoles")


# ---------- agile ----------

def _paginate_agile(fetch) -> list:
    """Walk a Jira Agile paged endpoint (uses `values` + `isLast` + `startAt`)
    until exhausted. `fetch(start, page)` must return the raw API dict."""
    out: list = []
    start = 0
    page = 50
    while True:
        resp = fetch(start, page) or {}
        values = resp.get("values", []) or []
        out.extend(values)
        if resp.get("isLast") is True or len(values) < page:
            break
        start += page
    return out


def list_boards(
    board_name: Optional[str] = None,
    project_key: Optional[str] = None,
    board_type: Optional[str] = None,
) -> dict:
    boards = _paginate_agile(
        lambda start, page: _jira.get_all_agile_boards(
            board_name=board_name,
            project_key=project_key,
            board_type=board_type,
            start=start,
            limit=page,
        )
    )
    return {"count": len(boards), "boards": boards}


def list_board_sprints(board_id: int, state: Optional[str] = None) -> dict:
    sprints = _paginate_agile(
        lambda start, page: _jira.get_all_sprints_from_board(
            board_id, state=state, start=start, limit=page
        )
    )
    return {"count": len(sprints), "sprints": sprints}


def get_sprint_issues(
    board_id: int,
    sprint_id: int,
    jql: str = "",
    fields: str = "summary,status,assignee,priority",
) -> dict:
    # The sprint-issues endpoint pages with startAt/maxResults/total, exposing
    # `issues` (not `values`) — so we can't reuse _paginate_agile directly.
    all_issues: list = []
    start = 0
    page = 50
    while True:
        resp = _jira.get_all_issues_for_sprint_in_board(
            board_id=board_id,
            sprint_id=sprint_id,
            jql=jql,
            fields=fields,
            start=start,
            limit=page,
        ) or {}
        batch = resp.get("issues", []) or []
        all_issues.extend(batch)
        total = resp.get("total")
        if total is not None and len(all_issues) >= total:
            break
        if len(batch) < page:
            break
        start += page
    return {"count": len(all_issues), "issues": all_issues}


# ---------- metadata ----------

def list_metadata() -> dict:
    """One-shot: all fields (system + custom) + all statuses + all priorities.
    Useful when the AI needs to resolve custom-field IDs, status names, or
    priority names before building a JQL query.

    Aggressive trim: each entry keeps only the keys the AI uses for JQL
    construction. Self URLs, icon URLs, translated names, schema IDs, and
    avatar URLs are dropped. Fields that Jira exposes on an issue but does
    NOT expose to JQL (aggregate computed values like `aggregateprogress`,
    sub-resources like `worklog` / `timetracking` / `thumbnail`, and fields
    with no `clauseNames`) are dropped entirely — the AI can't filter on
    them anyway, so listing them would just invite invalid JQL.

    Raw payload is ~61 KB; this trimmed version is ~9 KB.

    Edge case: for a handful of system fields the JQL clause name differs
    from both `id` and `name` (fixVersion/affectedVersion/watchers/level/
    remainingEstimate). We drop `clauseNames` here to save space, so the AI
    falls back to the localized `name` (in quoted form) for those. Works in
    practice, with rare misses on those ~7 fields.
    """
    fields = _jira.get_all_fields() or []
    statuses = _jira.get_all_statuses() or []
    priorities = _jira.get_all_priorities() or []
    return {
        "fields": [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "custom": f.get("custom", False),
            }
            for f in fields
            if f.get("clauseNames")
        ],
        "statuses": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "category": (s.get("statusCategory") or {}).get("name"),
            }
            for s in statuses
        ],
        "priorities": [
            {"id": p.get("id"), "name": p.get("name")}
            for p in priorities
        ],
    }
