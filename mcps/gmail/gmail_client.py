"""Gmail API wrapper with multi-account support."""

import base64
import json
import mimetypes
import re
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

from googleapiclient.discovery import build

from auth import load_credentials

BUILTIN_TAGS = {"important", "credentials", "contacts"}

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


def _plain_to_html(text: str) -> str:
    """Convert plain text to HTML with proper paragraph spacing."""
    import html as _html

    paragraphs = text.split("\n\n")
    html_parts = []
    for p in paragraphs:
        escaped = _html.escape(p)
        escaped = escaped.replace("\n", "<br>")
        html_parts.append(f"<p>{escaped}</p>")
    return "".join(html_parts)


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
        """Build an authenticated Gmail API service for an account.

        Always creates a fresh httplib2 connection to avoid stale SSL errors
        (EOF occurred in violation of protocol) in this long-lived MCP process.
        Cheap: static_discovery=True (default) loads from bundled JSON, no HTTP.
        """
        creds = load_credentials(alias)
        if creds is None:
            raise RuntimeError(
                f"No credentials for account '{alias}'. Run setup_auth.py to authenticate."
            )

        return build("gmail", "v1", credentials=creds)

    def _get_label_map(self, service) -> dict[str, str]:
        """Build label_id → label_name mapping for an account."""
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        return {label["id"]: label["name"] for label in labels}

    @staticmethod
    def _localize_date(raw: str) -> str:
        """Convert an RFC 2822 email date to the system's local timezone."""
        if not raw:
            return ""
        try:
            dt = parsedate_to_datetime(raw).astimezone()
            return dt.strftime("%Y-%m-%d %I:%M %p")
        except Exception:
            return raw

    @staticmethod
    def _has_attachments(payload: dict) -> bool:
        """Check if any part in the payload has a filename (i.e. is an attachment)."""
        for part in payload.get("parts", []):
            if part.get("filename"):
                return True
            if GmailClient._has_attachments(part):
                return True
        return False

    def _format_message(self, msg: dict, alias: str) -> dict:
        """Extract useful fields from a Gmail API message resource."""
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        return {
            "id": msg["id"],
            "threadId": msg.get("threadId"),
            "account": alias,
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": self._localize_date(headers.get("date", "")),
            "snippet": msg.get("snippet", ""),
            "labelIds": msg.get("labelIds", []),
            "has_attachments": self._has_attachments(payload),
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
                    "attachmentId": part.get("body", {}).get("attachmentId", ""),
                    "filename": part["filename"],
                    "mimeType": part.get("mimeType", ""),
                    "size": part.get("body", {}).get("size", 0),
                })
            attachments.extend(self._get_attachments_list(part))
        return attachments

    # Only fetch the fields needed for search results (headers + part filenames for has_attachments)
    _LIST_FIELDS = "id,threadId,labelIds,snippet,payload/headers,payload/parts/filename"

    def _batch_get_messages(self, service, message_ids: list[str], alias: str) -> list[dict]:
        """Fetch message metadata in batches of 1000 using Gmail's batch API."""
        fetched: list[dict] = []

        def _callback(request_id, response, exception):
            if exception is None:
                fetched.append(self._format_message(response, alias))

        for i in range(0, len(message_ids), 1000):
            batch = service.new_batch_http_request(callback=_callback)
            for msg_id in message_ids[i:i + 1000]:
                batch.add(
                    service.users().messages().get(
                        userId="me", id=msg_id, format="full",
                        fields=self._LIST_FIELDS,
                    )
                )
            batch.execute()

        return fetched

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

    def _mark_as_read(self, messages: list[dict]) -> None:
        """Mark search results as read. Uses threads().modify for multi-message
        threads (one call per thread) and messages().batchModify for standalone
        messages (one call per account)."""
        from collections import Counter

        thread_counts: Counter = Counter()
        for msg in messages:
            thread_counts[(msg["account"], msg.get("threadId"))] += 1

        thread_ids_by_account: dict[str, set[str]] = {}
        single_ids_by_account: dict[str, list[str]] = {}
        for msg in messages:
            alias = msg["account"]
            tid = msg.get("threadId")
            if thread_counts[(alias, tid)] > 1:
                thread_ids_by_account.setdefault(alias, set()).add(tid)
            else:
                single_ids_by_account.setdefault(alias, []).append(msg["id"])

        for alias, tids in thread_ids_by_account.items():
            service = self._get_service(alias)
            for tid in tids:
                service.users().threads().modify(
                    userId="me", id=tid, body={"removeLabelIds": ["UNREAD"]}
                ).execute()

        for alias, ids in single_ids_by_account.items():
            service = self._get_service(alias)
            service.users().messages().batchModify(
                userId="me", body={"ids": ids, "removeLabelIds": ["UNREAD"]}
            ).execute()

    # --- Public API ---

    def search_messages(
        self,
        query: str | None = None,
        date: str | None = None,
        from_email: str | None = None,
        max_results: int = 50,
        account: str | None = None,
        skip_ai: bool = True,
    ) -> dict:
        """Search emails. If account is None, searches all accounts.

        When skip_ai=True, emails with ai/* labels are excluded from results
        and their counts are returned in ai_skipped.
        """
        gmail_query = self._build_query(query, date, from_email)
        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        results = []
        label_maps: dict[str, dict[str, str]] = {}

        for alias in aliases:
            service = self._get_service(alias)
            if skip_ai:
                label_maps[alias] = self._get_label_map(service)
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=gmail_query or None, maxResults=max_results)
                .execute()
            )
            message_ids = [m["id"] for m in resp.get("messages", [])]
            results.extend(self._batch_get_messages(service, message_ids, alias))

        if not skip_ai:
            self._mark_as_read(results)
            return {"results": results, "ai_skipped": {}}

        unsorted = []
        skipped_counts: dict[str, int] = {}
        for msg in results:
            label_map = label_maps.get(msg["account"], {})
            auto_tags = [
                label_map[lid]
                for lid in msg.get("labelIds", [])
                if lid in label_map and label_map[lid].lower().startswith("ai/")
            ]
            if auto_tags:
                for tag in auto_tags:
                    skipped_counts[tag] = skipped_counts.get(tag, 0) + 1
            else:
                unsorted.append(msg)

        self._mark_as_read(unsorted)
        return {"results": unsorted, "ai_skipped": skipped_counts}

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

    def get_attachment_content(self, message_id: str, attachment_id: str, account: str) -> dict:
        """Download an attachment's binary content (base64url-encoded)."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)
        att = service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id
        ).execute()
        return {
            "data": att["data"],
            "size": att.get("size", 0),
        }

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

    def _build_message(
        self, to: str, subject: str, body: str,
        cc: str = "", bcc: str = "", attachments: list[str] | None = None,
    ) -> EmailMessage:
        """Build an EmailMessage with optional attachments (any file type)."""
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc
        msg.set_content(_plain_to_html(body), subtype="html")

        for file_path in (attachments or []):
            path = Path(file_path)
            if not path.exists():
                raise FileNotFoundError(f"Attachment not found: {path}")
            mime_type, _ = mimetypes.guess_type(str(path))
            mime_type = mime_type or "application/octet-stream"
            maintype, subtype = mime_type.split("/", 1)
            msg.add_attachment(
                path.read_bytes(),
                maintype=maintype, subtype=subtype,
                filename=path.name,
            )

        return msg

    def create_draft(
        self, to: str, subject: str, body: str, account: str,
        cc: str = "", bcc: str = "", attachments: list[str] | None = None,
    ) -> dict:
        """Create a draft email."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)

        message = self._build_message(to, subject, body, cc, bcc, attachments)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()

        return {"draftId": draft["id"], "account": alias}

    def _get_reply_headers(self, service, message_id: str) -> dict:
        """Fetch threadId and Message-ID header from an existing message for threading."""
        msg = (
            service.users()
            .messages()
            .get(
                userId="me", id=message_id, format="metadata",
                metadataHeaders=["Message-ID", "Message-Id"],
            )
            .execute()
        )
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        return {
            "threadId": msg.get("threadId"),
            "message_id_header": headers.get("message-id", ""),
        }

    def send_message(
        self, to: str, subject: str, body: str, account: str,
        cc: str = "", bcc: str = "",
        reply_to_message_id: str | None = None,
        attachments: list[str] | None = None,
    ) -> dict:
        """Send an email. If reply_to_message_id is set, sends as a thread reply."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)

        message = self._build_message(to, subject, body, cc, bcc, attachments)

        send_body: dict = {}
        if reply_to_message_id:
            reply_info = self._get_reply_headers(service, reply_to_message_id)
            if reply_info["message_id_header"]:
                message["In-Reply-To"] = reply_info["message_id_header"]
                message["References"] = reply_info["message_id_header"]
            if reply_info["threadId"]:
                send_body["threadId"] = reply_info["threadId"]

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_body["raw"] = raw
        sent = service.users().messages().send(userId="me", body=send_body).execute()

        return {"id": sent["id"], "threadId": sent.get("threadId"), "account": alias}

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
        {"tag": "ai/finance", "description": "AI-sorted payments, receipts, invoices, and bank notifications"},
    ]

    def _resolve_tag_to_label_id(self, tag: str, service) -> str:
        """Resolve a tag name to a Gmail label ID. Creates the label if it doesn't exist."""
        if tag == "important":
            return "STARRED"

        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if label["name"].lower() == tag.lower():
                return label["id"]

        created = service.users().labels().create(
            userId="me",
            body={"name": tag, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ).execute()
        return created["id"]

    def _resolve_tag_to_query(self, tag: str) -> str:
        """Resolve a tag name to a Gmail search query."""
        if tag == "important":
            return "is:starred"
        return f"label:{tag}"

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
            message_ids = [m["id"] for m in resp.get("messages", [])]
            results.extend(self._batch_get_messages(service, message_ids, alias))

        return results

    def list_tags(self, account: str | None = None) -> dict:
        """List all tags: built-in defaults + user-created labels per account."""
        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        default_names = {t["tag"] for t in self._DEFAULT_TAGS}
        accounts = {}

        for alias in aliases:
            service = self._get_service(alias)
            labels = service.users().labels().list(userId="me").execute().get("labels", [])
            custom = []
            for label in labels:
                if label.get("type") == "user" and label["name"].lower() not in default_names:
                    custom.append({"tag": label["name"], "label_id": label["id"]})
            accounts[alias] = custom

        return {
            "built_in": self._DEFAULT_TAGS,
            "accounts": accounts,
        }

    def delete_tag(self, tag: str, account: str | None = None) -> dict:
        """Permanently delete a tag (Gmail label) from one or all accounts.

        Cannot delete "important" — it maps to Gmail's STARRED system label.
        """
        if tag.lower() == "important":
            return {"status": "error", "message": "Cannot delete 'important' — it maps to Gmail's STARRED system label."}

        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        results = []

        for alias in aliases:
            service = self._get_service(alias)
            labels = service.users().labels().list(userId="me").execute().get("labels", [])
            label_id = None
            for label in labels:
                if label["name"].lower() == tag.lower() and label.get("type") == "user":
                    label_id = label["id"]
                    break

            if label_id is None:
                results.append({"account": alias, "status": "not_found"})
                continue

            service.users().labels().delete(userId="me", id=label_id).execute()
            results.append({"account": alias, "status": "deleted", "tag": tag})

        return {"tag": tag, "accounts": results}

    def rename_tag(self, old_tag: str, new_tag: str, account: str | None = None) -> dict:
        """Rename a tag (Gmail label) across one or all accounts.

        Cannot rename built-in tags (important, credentials, contacts).
        """
        if old_tag.lower() in BUILTIN_TAGS:
            return {"status": "error", "message": f"Cannot rename built-in tag '{old_tag}'."}

        aliases = [self._resolve_alias(account)] if account else self._get_all_aliases()
        results = []

        for alias in aliases:
            service = self._get_service(alias)
            labels = service.users().labels().list(userId="me").execute().get("labels", [])
            label_id = None
            label_name = None
            for label in labels:
                if label["name"].lower() == old_tag.lower() and label.get("type") == "user":
                    label_id = label["id"]
                    label_name = label["name"]
                    break

            if label_id is None:
                results.append({"account": alias, "status": "not_found"})
                continue

            if label_name == new_tag:
                results.append({"account": alias, "status": "no_change"})
                continue

            service.users().labels().patch(
                userId="me", id=label_id, body={"name": new_tag},
            ).execute()
            results.append({"account": alias, "status": "renamed", "old_tag": old_tag, "new_tag": new_tag})

        return {"old_tag": old_tag, "new_tag": new_tag, "accounts": results}

    def untrash_message(self, message_id: str, account: str) -> dict:
        """Recover a message from trash."""
        alias = self._resolve_alias(account)
        service = self._get_service(alias)
        service.users().messages().untrash(userId="me", id=message_id).execute()
        return {"id": message_id, "account": alias, "status": "untrashed"}

    def unsubscribe(self, message_id: str, account: str) -> dict:
        """Extract List-Unsubscribe header and attempt to unsubscribe.

        Priority: HTTP one-click POST (RFC 8058) → return URL for manual visit.
        """
        alias = self._resolve_alias(account)
        service = self._get_service(alias)
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["List-Unsubscribe", "List-Unsubscribe-Post", "From", "Subject"],
            )
            .execute()
        )

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        raw_unsub = headers.get("list-unsubscribe", "")
        has_one_click = "list-unsubscribe=one-click" in headers.get("list-unsubscribe-post", "").lower()

        if not raw_unsub:
            return {
                "id": message_id,
                "account": alias,
                "status": "no_unsubscribe_header",
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
            }

        # Parse mailto: and http(s): URLs from the header
        # Future: mailto unsubscribe via Gmail API send_message
        # mailto_match = re.search(r"<mailto:([^>]+)>", raw_unsub)
        http_match = re.search(r"<(https?://[^>]+)>", raw_unsub)

        http_url = http_match.group(1) if http_match else None

        # Try HTTP one-click unsubscribe (RFC 8058)
        if http_url and has_one_click:
            try:
                req = urllib.request.Request(
                    http_url,
                    data=b"List-Unsubscribe=One-Click",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return {
                        "id": message_id,
                        "account": alias,
                        "status": "unsubscribed",
                        "method": "one_click_http",
                        "http_status": resp.status,
                        "from": headers.get("from", ""),
                        "subject": headers.get("subject", ""),
                    }
            except Exception as e:
                # One-click failed, fall through to return URL
                return {
                    "id": message_id,
                    "account": alias,
                    "status": "one_click_failed",
                    "error": str(e),
                    "url": http_url,
                    "from": headers.get("from", ""),
                    "subject": headers.get("subject", ""),
                }

        # Fallback: return the URL for manual visit
        if http_url:
            return {
                "id": message_id,
                "account": alias,
                "status": "manual_url",
                "url": http_url,
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
            }

        return {
            "id": message_id,
            "account": alias,
            "status": "no_usable_link",
            "raw_header": raw_unsub,
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
        }

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
            message_ids = [m["id"] for m in resp.get("messages", [])]
            results.extend(self._batch_get_messages(service, message_ids, alias))

        return results
