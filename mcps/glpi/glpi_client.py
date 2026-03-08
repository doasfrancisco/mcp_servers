"""GLPI REST API wrapper with session caching."""

import json
import os
from datetime import date
from pathlib import Path

import requests
import urllib3
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_SESSION_FILE = Path(__file__).parent / ".session.json"


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
        sort: int = 1,
        order: str = "ASC",
        search_text: dict | None = None,
        is_deleted: bool = False,
        expand_dropdowns: bool = False,
    ) -> list | dict:
        params = {
            "range": range_str,
            "sort": sort,
            "order": order,
        }
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

    def search_tickets_today(self) -> dict:
        today = date.today().isoformat()
        return self.search_items(
            "Ticket",
            criteria=[
                {"field": 15, "searchtype": "morethan", "value": f"{today} 00:00:00"},
            ],
            forcedisplay=[1, 2, 7, 12, 15],
            range_str="0-100",
        )

    def kill_session(self):
        try:
            self._get("/killSession")
        finally:
            self._session_token = None
            if _SESSION_FILE.exists():
                _SESSION_FILE.unlink()
