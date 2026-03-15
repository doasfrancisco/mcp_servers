"""Google Drive API wrapper with multi-account support."""

import io
import json
import re
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from auth import load_credentials

FOLDER_MIME = "application/vnd.google-apps.folder"

# Google Workspace MIME types → export formats
EXPORT_MIME_MAP = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": "image/png",
}

# MIME types safe to download as text
TEXT_MIMES = {
    "text/", "application/json", "application/xml", "application/javascript",
    "application/x-yaml", "application/toml", "application/csv",
}

# Permission role priority for auto-account resolution
_ROLE_PRIORITY = {"owner": 3, "organizer": 2, "writer": 1, "commenter": 0, "reader": -1}

MAX_TEXT_DOWNLOAD = 5 * 1024 * 1024  # 5MB


def _download_file(service, file_id: str) -> bytes:
    """Download file content using chunked streaming."""
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def _extract_docx_text(data: bytes) -> str:
    """Extract text from .docx bytes (headers, paragraphs, tables, footers)."""
    doc = Document(io.BytesIO(data))
    parts = []

    def _extract_from_container(container):
        for item in container.iter_inner_content():
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if text:
                    parts.append(text)
            elif isinstance(item, Table):
                for row in item.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    parts.append("\t".join(cells))

    # Headers
    for section in doc.sections:
        _extract_from_container(section.header)

    # Body
    _extract_from_container(doc)

    # Footers
    for section in doc.sections:
        _extract_from_container(section.footer)

    return "\n".join(parts)


_OFFICE_EXTRACTORS = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _extract_docx_text,
}


class AccountConfig:
    def __init__(self, email: str, alias: str):
        self.email = email
        self.alias = alias


def _load_accounts_config() -> dict:
    config_path = Path(__file__).parent / "accounts.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Accounts config not found at {config_path}. "
            "Copy accounts.json.example to accounts.json and configure your accounts."
        )
    return json.loads(config_path.read_text())


def extract_file_id(url_or_id: str) -> str:
    """Extract a file/folder ID from a Google Drive URL or raw ID."""
    # Folder URLs: /folders/ID
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url_or_id)
    if m:
        return m.group(1)
    # File URLs: /d/ID or /file/d/ID (Drive, Docs, Sheets, Slides)
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url_or_id)
    if m:
        return m.group(1)
    # Raw ID
    if re.match(r"^[a-zA-Z0-9_-]+$", url_or_id):
        return url_or_id
    raise ValueError(f"Could not extract file/folder ID from: {url_or_id}")


def _is_text_mime(mime_type: str) -> bool:
    return any(mime_type.startswith(prefix) for prefix in TEXT_MIMES)


class DriveClient:
    """Multi-account Google Drive API client."""

    def __init__(self):
        self._accounts: dict[str, AccountConfig] = {}
        self._alias_to_email: dict[str, str] = {}
        self._email_to_alias: dict[str, str] = {}
        self._default_alias: str | None = None
        self._load_config()

    def _load_config(self):
        config = _load_accounts_config()
        self._default_alias = config.get("default")
        for acc in config["accounts"]:
            account = AccountConfig(acc["email"], acc["alias"])
            self._accounts[acc["alias"]] = account
            self._alias_to_email[acc["alias"]] = acc["email"]
            self._email_to_alias[acc["email"]] = acc["alias"]

    def _resolve_alias(self, account: str | None) -> str:
        """Resolve an account identifier (email or alias) to an alias."""
        if account is None:
            if self._default_alias:
                return self._default_alias
            raise ValueError("No account specified and no default configured.")
        if account in self._accounts:
            return account
        if account in self._email_to_alias:
            return self._email_to_alias[account]
        raise ValueError(
            f"Unknown account '{account}'. "
            f"Available: {', '.join(self._accounts.keys())}"
        )

    def _get_service(self, alias: str):
        """Build authenticated Drive v3 service."""
        creds = load_credentials(alias)
        if creds is None:
            raise RuntimeError(
                f"No credentials for account '{alias}'. Re-run setup."
            )
        return build("drive", "v3", credentials=creds)

    def _all_aliases(self) -> list[str]:
        return list(self._accounts.keys())

    # ── Auto-account resolution ────────────────────────────────────────

    def _best_account_for_file(self, file_id: str) -> str:
        """Try all accounts and return the alias with highest permission."""
        best_alias = None
        best_priority = -999

        for alias in self._all_aliases():
            try:
                service = self._get_service(alias)
                meta = service.files().get(
                    fileId=file_id,
                    fields="permissions(role,emailAddress)",
                    supportsAllDrives=True,
                ).execute()

                email = self._alias_to_email[alias]
                for perm in meta.get("permissions", []):
                    if perm.get("emailAddress", "").lower() == email.lower():
                        priority = _ROLE_PRIORITY.get(perm["role"], -1)
                        if priority > best_priority:
                            best_priority = priority
                            best_alias = alias
                        break
                else:
                    # No matching permission found but access worked → at least reader
                    if best_alias is None:
                        best_alias = alias
                        best_priority = -1
            except Exception:
                continue

        if best_alias is None:
            raise ValueError(
                f"No account has access to file '{file_id}'. "
                f"Tried: {', '.join(self._all_aliases())}"
            )
        return best_alias

    def _first_account_with_access(self, file_id: str) -> str:
        """Return the first account that can access a file."""
        for alias in self._all_aliases():
            try:
                service = self._get_service(alias)
                service.files().get(
                    fileId=file_id, fields="id", supportsAllDrives=True,
                ).execute()
                return alias
            except Exception:
                continue
        raise ValueError(
            f"No account has access to file '{file_id}'. "
            f"Tried: {', '.join(self._all_aliases())}"
        )

    # ── List files ─────────────────────────────────────────────────────

    def list_files(self, folder_id: str, recursive: bool = True) -> list[dict]:
        """List files in a folder, trying all accounts and merging results."""
        all_files = {}  # id → file dict (dedup across accounts)

        for alias in self._all_aliases():
            try:
                service = self._get_service(alias)
                files = self._list_files_for_account(
                    service, folder_id, recursive, alias,
                )
                for f in files:
                    if f["id"] not in all_files:
                        all_files[f["id"]] = f
            except Exception:
                continue

        if not all_files:
            raise ValueError(
                f"No account can access folder '{folder_id}'. "
                f"Tried: {', '.join(self._all_aliases())}"
            )
        return sorted(all_files.values(), key=lambda f: f.get("name", "").lower())

    def _list_files_for_account(
        self, service, folder_id: str, recursive: bool, alias: str, path: str = "",
    ) -> list[dict]:
        items = []
        page_token = None
        while True:
            resp = service.files().list(
                q=f'"{folder_id}" in parents and trashed=false',
                pageSize=100,
                pageToken=page_token,
                fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

            for f in resp.get("files", []):
                entry = {
                    "id": f["id"],
                    "name": f["name"],
                    "mimeType": f["mimeType"],
                    "size": f.get("size"),
                    "modifiedTime": f.get("modifiedTime"),
                    "path": f"{path}/{f['name']}" if path else f["name"],
                    "account": alias,
                }
                if f["mimeType"] == FOLDER_MIME:
                    entry["type"] = "folder"
                else:
                    entry["type"] = "file"

                items.append(entry)

                if recursive and f["mimeType"] == FOLDER_MIME:
                    children = self._list_files_for_account(
                        service, f["id"], True, alias, entry["path"],
                    )
                    items.extend(children)

            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return items

    # ── Read file ──────────────────────────────────────────────────────

    def read_file(self, file_id: str) -> dict:
        """Read file content, auto-resolving account with best permission."""
        alias = self._best_account_for_file(file_id)
        service = self._get_service(alias)

        meta = service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, size, modifiedTime, webViewLink",
            supportsAllDrives=True,
        ).execute()

        mime = meta["mimeType"]
        result = {
            "id": meta["id"],
            "name": meta["name"],
            "mimeType": mime,
            "size": meta.get("size"),
            "modifiedTime": meta.get("modifiedTime"),
            "webViewLink": meta.get("webViewLink"),
            "account": alias,
        }

        # Google Workspace files → export
        if mime in EXPORT_MIME_MAP:
            export_mime = EXPORT_MIME_MAP[mime]
            try:
                content = service.files().export(
                    fileId=file_id, mimeType=export_mime,
                ).execute()
                if isinstance(content, bytes):
                    result["content"] = content.decode("utf-8", errors="replace")
                else:
                    result["content"] = str(content)
            except Exception as e:
                result["content"] = f"[export failed: {e}]"
            return result

        # Text files → download
        size = int(meta.get("size", 0))
        if _is_text_mime(mime) and size <= MAX_TEXT_DOWNLOAD:
            try:
                content = _download_file(service, file_id)
                result["content"] = content.decode("utf-8", errors="replace")
            except Exception as e:
                result["content"] = f"[download failed: {e}]"
            return result

        # Office documents → download + extract text
        extractor = _OFFICE_EXTRACTORS.get(mime)
        if extractor and size <= MAX_TEXT_DOWNLOAD:
            try:
                data = _download_file(service, file_id)
                result["content"] = extractor(data)
            except Exception as e:
                result["content"] = f"[extraction failed: {e}]"
            return result

        # Binary or too large
        if size > MAX_TEXT_DOWNLOAD:
            result["content"] = f"[file too large to read: {size} bytes, limit {MAX_TEXT_DOWNLOAD}]"
        else:
            result["content"] = f"[binary file: {mime}, {size} bytes — download not supported via MCP]"
        return result

    # ── Search files ───────────────────────────────────────────────────

    def search_files(
        self,
        name: str | None = None,
        query: str | None = None,
        max_results: int = 50,
    ) -> list[dict]:
        """Search files across all accounts."""
        clauses = ["trashed=false"]
        if name:
            escaped = name.replace("'", "\\'")
            clauses.append(f"name contains '{escaped}'")
        if query:
            escaped = query.replace("'", "\\'")
            clauses.append(f"fullText contains '{escaped}'")

        q = " and ".join(clauses)
        all_files = {}

        for alias in self._all_aliases():
            try:
                service = self._get_service(alias)
                collected = 0
                page_token = None
                while collected < max_results:
                    page_size = min(100, max_results - collected)
                    resp = service.files().list(
                        q=q,
                        pageSize=page_size,
                        pageToken=page_token,
                        fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    ).execute()

                    for f in resp.get("files", []):
                        if f["id"] not in all_files:
                            all_files[f["id"]] = {
                                "id": f["id"],
                                "name": f["name"],
                                "mimeType": f["mimeType"],
                                "size": f.get("size"),
                                "modifiedTime": f.get("modifiedTime"),
                                "type": "folder" if f["mimeType"] == FOLDER_MIME else "file",
                                "account": alias,
                            }
                            collected += 1
                    page_token = resp.get("nextPageToken")
                    if not page_token:
                        break
            except Exception:
                continue

        results = sorted(all_files.values(), key=lambda f: f.get("name", "").lower())
        return results[:max_results]

    # ── Move files ─────────────────────────────────────────────────────

    def move_files(
        self, file_ids: list[str], dest_folder_id: str, account: str,
    ) -> list[dict]:
        """Move files to a destination folder."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)
        results = []

        for fid in file_ids:
            try:
                file_meta = service.files().get(
                    fileId=fid, fields="name, parents", supportsAllDrives=True,
                ).execute()
                previous_parents = ",".join(file_meta.get("parents", []))
                service.files().update(
                    fileId=fid,
                    addParents=dest_folder_id,
                    removeParents=previous_parents,
                    supportsAllDrives=True,
                    fields="id, parents",
                ).execute()
                results.append({"id": fid, "name": file_meta["name"], "status": "moved"})
            except Exception as e:
                results.append({"id": fid, "status": "error", "error": str(e)})

        return results

    # ── Delete files (trash) ───────────────────────────────────────────

    def delete_files(self, file_ids: list[str], account: str) -> list[dict]:
        """Trash files."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)
        results = []

        for fid in file_ids:
            try:
                file_meta = service.files().get(
                    fileId=fid, fields="name", supportsAllDrives=True,
                ).execute()
                service.files().update(
                    fileId=fid,
                    body={"trashed": True},
                    supportsAllDrives=True,
                    fields="id",
                ).execute()
                results.append({"id": fid, "name": file_meta["name"], "status": "trashed"})
            except Exception as e:
                results.append({"id": fid, "status": "error", "error": str(e)})

        return results

    # ── Create file ────────────────────────────────────────────────────

    def create_file(
        self,
        name: str,
        account: str,
        parent_id: str | None = None,
        content: str | None = None,
        mime_type: str = "text/plain",
    ) -> dict:
        """Create a new file in Google Drive."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)

        body: dict = {"name": name, "mimeType": mime_type}
        if parent_id:
            body["parents"] = [parent_id]

        if content:
            from googleapiclient.http import MediaIoBaseUpload
            media = MediaIoBaseUpload(
                io.BytesIO(content.encode("utf-8")),
                mimetype=mime_type,
                resumable=False,
            )
            result = service.files().create(
                body=body,
                media_body=media,
                supportsAllDrives=True,
                fields="id, name, mimeType, webViewLink",
            ).execute()
        else:
            result = service.files().create(
                body=body,
                supportsAllDrives=True,
                fields="id, name, mimeType, webViewLink",
            ).execute()

        return result

    # ── Create folder ──────────────────────────────────────────────────

    def create_folder(
        self, name: str, account: str, parent_id: str | None = None,
    ) -> dict:
        """Create a new folder in Google Drive."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)

        body: dict = {"name": name, "mimeType": FOLDER_MIME}
        if parent_id:
            body["parents"] = [parent_id]

        result = service.files().create(
            body=body,
            supportsAllDrives=True,
            fields="id, name, mimeType, webViewLink",
        ).execute()

        return result
