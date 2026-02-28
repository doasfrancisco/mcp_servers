"""Gmail API wrapper with multi-account support."""

import base64
import json
from email.mime.text import MIMEText
from pathlib import Path

from googleapiclient.discovery import build

from auth import load_credentials

# Date shorthand → Gmail query mapping
_DATE_SHORTHANDS = {
    "today": "newer_than:1d",
    "last_24h": "newer_than:1d",
    "yesterday": "newer_than:2d older_than:1d",
    "last_7d": "newer_than:7d",
    "last_30d": "newer_than:30d",
    "last_week": "newer_than:7d",
    "last_month": "newer_than:30d",
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


class GmailClient:
    """Multi-account Gmail API client."""

    def __init__(self):
        self._services: dict[str, object] = {}
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
            return self._default_alias
        if account in self._accounts:
            return account
        if account in self._email_to_alias:
            return self._email_to_alias[account]
        raise ValueError(
            f"Unknown account '{account}'. "
            f"Available: {list(self._accounts.keys())} or {list(self._email_to_alias.keys())}"
        )

    def _get_all_aliases(self) -> list[str]:
        return list(self._accounts.keys())

    def _get_service(self, alias: str):
        """Get or create an authenticated Gmail API service for an account."""
        if alias in self._services:
            return self._services[alias]

        creds = load_credentials(alias)
        if creds is None:
            raise RuntimeError(
                f"No credentials for account '{alias}'. Run setup_auth.py to authenticate."
            )

        service = build("gmail", "v1", credentials=creds)
        self._services[alias] = service
        return service

    def _format_message(self, msg: dict, alias: str) -> dict:
        """Extract useful fields from a Gmail API message resource."""
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        return {
            "id": msg["id"],
            "threadId": msg.get("threadId"),
            "account": alias,
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
            "labelIds": msg.get("labelIds", []),
        }

    def _get_body(self, payload: dict) -> str:
        """Recursively extract the text body from a message payload."""
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        for part in payload.get("parts", []):
            body = self._get_body(part)
            if body:
                return body
        return ""

    def _get_attachments_list(self, payload: dict) -> list[dict]:
        """List attachment metadata from a message payload."""
        attachments = []
        for part in payload.get("parts", []):
            if part.get("filename"):
                attachments.append({
                    "filename": part["filename"],
                    "mimeType": part.get("mimeType", ""),
                    "size": part.get("body", {}).get("size", 0),
                })
            attachments.extend(self._get_attachments_list(part))
        return attachments

    def _build_query(self, query: str | None, date: str | None, from_email: str | None) -> str:
        """Build a Gmail search query from convenience params."""
        parts = []
        if query:
            parts.append(query)
        if date:
            shorthand = _DATE_SHORTHANDS.get(date.lower())
            if shorthand:
                parts.append(shorthand)
            else:
                parts.append(date)
        if from_email:
            parts.append(f"from:{from_email}")
        return " ".join(parts)

    # --- Public API ---

    def get_profile(self, account: str | None = None) -> list[dict]:
        """Get profile info. If account is None, returns all accounts."""
        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        results = []
        for alias in aliases:
            service = self._get_service(alias)
            profile = service.users().getProfile(userId="me").execute()
            results.append({
                "account": alias,
                "email": profile.get("emailAddress"),
                "messagesTotal": profile.get("messagesTotal"),
                "threadsTotal": profile.get("threadsTotal"),
                "historyId": profile.get("historyId"),
            })
        return results

    def search_messages(
        self,
        query: str | None = None,
        date: str | None = None,
        from_email: str | None = None,
        max_results: int = 50,
        account: str | None = None,
    ) -> list[dict]:
        """Search emails. If account is None, searches all accounts."""
        gmail_query = self._build_query(query, date, from_email)
        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        results = []

        for alias in aliases:
            service = self._get_service(alias)
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=gmail_query or None, maxResults=max_results)
                .execute()
            )
            messages = resp.get("messages", [])
            for msg_ref in messages:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_ref["id"], format="metadata",
                         metadataHeaders=["From", "To", "Subject", "Date"])
                    .execute()
                )
                results.append(self._format_message(msg, alias))

        return results

    def read_message(self, message_id: str, account: str) -> dict:
        """Read a specific email by ID."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        formatted = self._format_message(msg, alias)
        formatted["body"] = self._get_body(msg.get("payload", {}))
        formatted["attachments"] = self._get_attachments_list(msg.get("payload", {}))
        return formatted

    def read_thread(self, thread_id: str, account: str) -> dict:
        """Read a full email thread."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)
        thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        messages = []
        for msg in thread.get("messages", []):
            formatted = self._format_message(msg, alias)
            formatted["body"] = self._get_body(msg.get("payload", {}))
            messages.append(formatted)
        return {"threadId": thread_id, "account": alias, "messages": messages}

    def list_drafts(self, account: str | None = None) -> list[dict]:
        """List draft emails. If account is None, lists from all accounts."""
        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        results = []

        for alias in aliases:
            service = self._get_service(alias)
            resp = service.users().drafts().list(userId="me").execute()
            for draft in resp.get("drafts", []):
                draft_detail = service.users().drafts().get(userId="me", id=draft["id"]).execute()
                msg = draft_detail.get("message", {})
                formatted = self._format_message(msg, alias)
                formatted["draftId"] = draft["id"]
                results.append(formatted)

        return results

    def create_draft(self, to: str, subject: str, body: str, account: str, cc: str = "", bcc: str = "") -> dict:
        """Create a draft email."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()

        return {"draftId": draft["id"], "account": alias}

    def send_message(self, to: str, subject: str, body: str, account: str, cc: str = "", bcc: str = "") -> dict:
        """Send an email."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()

        return {"id": sent["id"], "threadId": sent.get("threadId"), "account": alias}

    def trash_message(self, message_id: str, account: str) -> dict:
        """Move a message to trash."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)
        service.users().messages().trash(userId="me", id=message_id).execute()
        return {"id": message_id, "account": alias, "status": "trashed"}

    def trash_messages(self, messages: list[dict]) -> dict:
        """Move multiple messages to trash, grouped by account into batchModify calls."""
        by_account: dict[str, list[str]] = {}
        for msg in messages:
            alias = self._resolve_alias(msg["account"])
            by_account.setdefault(alias, []).append(msg["id"])

        results = []
        for alias, ids in by_account.items():
            service = self._get_service(alias)
            service.users().messages().batchModify(
                userId="me",
                body={"ids": ids, "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]},
            ).execute()
            results.append({"account": alias, "count": len(ids), "status": "trashed"})

        return {"total": sum(r["count"] for r in results), "accounts": results}

    # Default tags always shown in list_tags, even before first use
    _DEFAULT_TAGS = [
        {"tag": "important", "description": "Starred emails — actionable, urgent, needs attention"},
        {"tag": "credentials", "description": "Passwords, API keys, server access, login details"},
        {"tag": "contacts", "description": "Emails from people you care about maintaining a relationship with"},
    ]

    def _resolve_tag_to_label_id(self, tag: str, service) -> str:
        """Resolve a tag name to a Gmail label ID. Creates the label if it doesn't exist."""
        if tag == "important":
            return "STARRED"

        label_name = f"claude/{tag}"
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if label["name"].lower() == label_name.lower():
                return label["id"]

        created = service.users().labels().create(
            userId="me",
            body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ).execute()
        return created["id"]

    def _resolve_tag_to_query(self, tag: str) -> str:
        """Resolve a tag name to a Gmail search query."""
        if tag == "important":
            return "is:starred"
        return f"label:claude/{tag}"

    def tag_messages_batch(self, messages: list[dict]) -> dict:
        """Process per-message tag operations. Groups by (account, tag, remove_tag) for efficiency."""
        # Group messages by (alias, tag, remove_tag) so each unique combo is one batchModify
        groups: dict[tuple[str, str | None, str | None], list[str]] = {}
        for msg in messages:
            alias = self._resolve_alias(msg["account"])
            key = (alias, msg.get("tag"), msg.get("remove_tag"))
            groups.setdefault(key, []).append(msg["id"])

        results = []
        for (alias, tag, remove_tag), ids in groups.items():
            if not tag and not remove_tag:
                continue
            service = self._get_service(alias)
            body: dict = {"ids": ids}
            if tag:
                body["addLabelIds"] = [self._resolve_tag_to_label_id(tag, service)]
            if remove_tag:
                body["removeLabelIds"] = [self._resolve_tag_to_label_id(remove_tag, service)]
            service.users().messages().batchModify(userId="me", body=body).execute()

            status = f"{remove_tag} → {tag}" if remove_tag and tag else f"added {tag}" if tag else f"removed {remove_tag}"
            results.append({"account": alias, "count": len(ids), "tag": tag, "remove_tag": remove_tag, "status": status})

        return {"total": sum(r["count"] for r in results), "accounts": results}

    def get_tagged(self, tag: str, max_results: int = 50, account: str | None = None) -> list[dict]:
        """Get messages with a specific tag."""
        query = self._resolve_tag_to_query(tag)
        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        results = []

        for alias in aliases:
            service = self._get_service(alias)
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            for msg_ref in resp.get("messages", []):
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_ref["id"], format="metadata",
                         metadataHeaders=["From", "To", "Subject", "Date"])
                    .execute()
                )
                results.append(self._format_message(msg, alias))

        return results

    def list_tags(self, account: str | None = None) -> list[dict]:
        """List all tags (defaults + claude/* custom labels from Gmail)."""
        tags = list(self._DEFAULT_TAGS)
        default_names = {t["tag"] for t in self._DEFAULT_TAGS}
        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        seen = set()

        for alias in aliases:
            service = self._get_service(alias)
            labels = service.users().labels().list(userId="me").execute().get("labels", [])
            for label in labels:
                if label["name"].lower().startswith("claude/"):
                    tag_name = label["name"].split("/", 1)[1]
                    if tag_name not in seen and tag_name not in default_names:
                        seen.add(tag_name)
                        tags.append({"tag": tag_name, "label_id": label["id"], "account": alias})

        return tags

    def untrash_message(self, message_id: str, account: str) -> dict:
        """Recover a message from trash."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)
        service.users().messages().untrash(userId="me", id=message_id).execute()
        return {"id": message_id, "account": alias, "status": "untrashed"}

    def list_trash(self, max_results: int = 50, account: str | None = None) -> list[dict]:
        """List messages in trash. If account is None, lists from all accounts."""
        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        results = []

        for alias in aliases:
            service = self._get_service(alias)
            resp = (
                service.users()
                .messages()
                .list(userId="me", q="in:trash", maxResults=max_results)
                .execute()
            )
            for msg_ref in resp.get("messages", []):
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_ref["id"], format="metadata",
                         metadataHeaders=["From", "To", "Subject", "Date"])
                    .execute()
                )
                results.append(self._format_message(msg, alias))

        return results
