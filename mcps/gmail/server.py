"""Gmail MCP Server — full Gmail control with multi-account support."""

import json
import logging
import webbrowser
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated

# 5 MB per file, keep current + 1 backup = 10 MB max
_log_dir = Path(__file__).parent / "logs"
_log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[RotatingFileHandler(_log_dir / "gmail.log", maxBytes=5_000_000, backupCount=1)],
)

from fastmcp import Context, FastMCP
from pydantic import BaseModel, BeforeValidator, model_validator

from gmail_client import BUILTIN_TAGS, GmailClient
from setup_server import is_setup_complete, needs_setup, start_setup_server


def _parse_json_str(v):
    """MCP clients may send lists as stringified JSON — parse before validation."""
    if isinstance(v, str):
        return json.loads(v)
    return v


class MessageRef(BaseModel):
    id: str
    account: str



def _ai_prefix(tag: str | None) -> str | None:
    """Prepend 'ai/' to custom tags so AI-sorted mail is easy to filter out."""
    if tag is None:
        return None
    if tag in BUILTIN_TAGS or tag.startswith("ai/"):
        return tag
    if "/" in tag:
        # Strip any existing prefix (auto/, foo/, etc.) and re-add ai/
        return f"ai/{tag.split('/', 1)[1]}"
    return f"ai/{tag}"


class TagOp(BaseModel):
    id: str
    account: str
    tag: str | None = None
    remove_tag: str | None = None

    @model_validator(mode="after")
    def _prefix_tags(self):
        self.tag = _ai_prefix(self.tag)
        return self


MessagesList = Annotated[list[MessageRef], BeforeValidator(_parse_json_str)]
TagOpList = Annotated[list[TagOp], BeforeValidator(_parse_json_str)]


# ── Auto-setup on first run ───────────────────────────────────────────

_setup_port: int | None = None


@asynccontextmanager
async def _lifespan(server):
    global _setup_port
    if needs_setup():
        _setup_port = start_setup_server()
        webbrowser.open(f"http://localhost:{_setup_port}")
    yield


mcp = FastMCP(
    "Gmail",
    lifespan=_lifespan,
    instructions="""IMPORTANT: Always discover a tool's schema with ToolSearch BEFORE calling it for the first time.

Before executing any write operation (trash, tag, send, create draft), always tell the user exactly what you're about to do and STOP your turn. Do NOT call the tool in the same message. Wait for the user to reply with confirmation before making the call.

When presenting email results to the user, always:
- Group by account (personal, work, university)
- Number each email sequentially within its account group (1., 2., 3.)
- Show the count per account
- Bold the sender name: **Sender** — Subject

Tag system for organizing emails:
- "important" → starred emails — actionable, urgent, needs attention
- "credentials" → passwords, API keys, server access, login details
- "contacts" → emails from people the user cares about maintaining a relationship with
Custom tags beyond these three are also supported and auto-created on first use.

Auto-sorted emails:
- Emails tagged with "ai/*" labels (e.g. "ai/finance") have already been reviewed and sorted by the AI.
- gmail_search_messages always excludes ai/* emails and returns their counts in "ai_skipped".
- Always show the ai_skipped summary to the user (e.g. "Also sorted: ai/programming (1), ai/finance (3)").
- To see auto-sorted emails, use gmail_get_tagged("ai/finance") — NOT gmail_search_messages.

Search behavior:
- When the user asks to "show emails", "check email", or similar — just call gmail_search_messages immediately. Do not plan, ask clarifying questions, or add extra steps.
- Always use the default max_results (100). Do not override it.

Attachments:
- When gmail_read_message downloads attachments, immediately read them using the Read tool — do NOT ask the user first. The "hint" field in each attachment tells you the file path to read.
- Reading is not a write operation — no confirmation needed.
- For binary files (Excel .xlsx, .pptx, etc.), the Read tool won't work. Use Python (openpyxl, pandas) or the appropriate skill to read them instead.
""",
)

_client: GmailClient | None = None


def _get_client() -> GmailClient:
    """Get the Gmail client, or raise a setup message if not configured."""
    global _client
    if needs_setup():
        if _setup_port and not is_setup_complete():
            raise RuntimeError(
                f"Gmail setup in progress. Complete the setup in your browser "
                f"(http://localhost:{_setup_port}), then try again."
            )
        if needs_setup():
            # Setup server not running or setup failed — start it
            port = start_setup_server()
            webbrowser.open(f"http://localhost:{port}")
            raise RuntimeError(
                f"Gmail is not configured. A setup page opened in your browser "
                f"(http://localhost:{port}). Add your Gmail accounts there, then try again."
            )
    if _client is None:
        _client = GmailClient()
    return _client


def _json(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _extract_sender_name(from_header: str) -> str:
    """Extract display name from 'Name <email>' or return email."""
    if "<" in from_header:
        return from_header.split("<")[0].strip().strip('"')
    return from_header


def _label_badges(label_ids: list[str]) -> str:
    """Turn labelIds into readable badges."""
    badges = []
    for lid in label_ids:
        if lid == "UNREAD":
            badges.append("🔵 unread")
        elif lid == "STARRED":
            badges.append("⭐ starred")
        elif lid == "IMPORTANT":
            badges.append("❗ important")
        elif lid not in ("INBOX", "SENT", "CATEGORY_PERSONAL", "CATEGORY_UPDATES",
                         "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"):
            badges.append(lid.lower())
    return " · ".join(badges)


def _format_search_md(data: dict) -> str:
    """Format search results as markdown grouped by account."""
    results = data.get("results", [])
    ai_skipped = data.get("ai_skipped", {})

    if not results and not ai_skipped:
        return "No emails found."

    # Group by account
    grouped: dict[str, list[dict]] = {}
    for msg in results:
        grouped.setdefault(msg["account"], []).append(msg)

    lines: list[str] = []
    for acct, msgs in grouped.items():
        lines.append(f"### {acct} ({len(msgs)})")
        lines.append("")
        for i, msg in enumerate(msgs, 1):
            sender = _extract_sender_name(msg["from"])
            subj = msg["subject"] or "(no subject)"
            att = " [attachment]" if msg.get("has_attachments") else ""
            badges = _label_badges(msg.get("labelIds", []))
            badge_str = f" [{badges}]" if badges else ""
            lines.append(f"{i}. **{sender}** — {subj}{att}{badge_str}")
            lines.append(f"   To: {msg.get('to', '')}")
            lines.append(f"   {msg['date']} · id:`{msg['id']}` · thread:`{msg.get('threadId', '')}`")
            snippet = msg.get("snippet", "")
            if snippet:
                lines.append(f"   > {snippet}")
            lines.append("")
        lines.append("")

    if ai_skipped:
        parts = [f"{tag} ({count})" for tag, count in ai_skipped.items()]
        lines.append(f"Also sorted: {', '.join(parts)}")

    return "\n".join(lines)


@mcp.tool()
async def gmail_search_messages(
    ctx: Context,
    query: str = "newer_than:1d",
    from_email: str | None = None,
    max_results: int = 100,
    account: str | None = None,
) -> str:
    """Search emails. Call immediately when user asks to show/check email — no planning needed.
    Auto-sorted emails (ai/*) are excluded — use gmail_get_tagged to see them.
    Returns markdown-formatted results.

    Args:
        query: Gmail search query. Defaults to "newer_than:1d" (today's emails).
            Supports all Gmail operators including date filters
            (e.g. "newer_than:1d", "after:2026/03/25", "subject:invoice is:unread").
        from_email: Filter by sender email address.
        max_results: Always use the default (100). Do not override.
        account: Email or alias. Omit to search all accounts.
    """
    if account:
        response = await ctx.elicit(
            message=f"Are you sure you want to search emails only for {account}?",
        )
        if response.action != "accept":
            account = None
    data = _get_client().search_messages(
        query=query, from_email=from_email,
        max_results=max_results, account=account,
    )
    return _format_search_md(data)


_BINARY_EXTENSIONS = {".xlsx", ".xls", ".pptx", ".doc", ".zip", ".rar", ".7z", ".tar", ".gz"}


def _download_hint(filename: str, path: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if f".{ext}" in _BINARY_EXTENSIONS:
        return f"Binary file saved to '{path}'. Use Python (openpyxl, etc.) or the appropriate skill to read it."
    return f"Use the Read tool on '{path}' to view this file."


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


@mcp.tool()
async def gmail_read_message(message_id: str, account: str, ctx: Context) -> str:
    """Read a specific email by message ID. Returns headers, body, and attachments.

    Readable attachments (PDF, Word, text < 5 MB) are extracted inline.
    Other files (images, Excel, archives, video) prompt you to download to ~/Downloads/.

    Args:
        message_id: The Gmail message ID (from search results).
        account: Email or alias — required to identify which account owns this message.
    """
    client = _get_client()
    result = client.read_message(message_id, account)

    # Handle password-protected PDFs
    protected = [a for a in result["attachments"] if a.get("password_protected")]
    for att in protected:
        pw_result = await ctx.elicit(
            f"'{att['filename']}' is password-protected. Enter the password to read it:",
            response_type=str,
        )
        if pw_result.action == "accept":
            try:
                att["content"] = client.read_pdf_with_password(
                    message_id, att["attachmentId"], pw_result.data, account,
                )
                del att["password_protected"]
            except Exception:
                att["error"] = "Wrong password or unreadable PDF"

    # Handle downloadable attachments
    downloadable = [a for a in result["attachments"] if a.get("downloadable")]
    if downloadable:
        file_list = "\n".join(
            f"- {a['filename']} ({_format_size(a['size'])})" for a in downloadable
        )
        elicit_result = await ctx.elicit(
            f"This email has files that can be downloaded:\n{file_list}\n\nSave to ~/Downloads?",
            response_type=None,
        )
        if elicit_result.action == "accept":
            for a in downloadable:
                dl = client.download_attachment(
                    message_id, a["attachmentId"], a["filename"], account,
                )
                a["downloaded_to"] = dl["path"]
                a["hint"] = _download_hint(a["filename"], dl["path"])
                del a["attachmentId"]
                del a["downloadable"]

    return _json(result)


@mcp.tool()
def gmail_read_thread(thread_id: str, account: str) -> str:
    """Read a full email thread by thread ID. Returns all messages in the thread.

    Args:
        thread_id: The Gmail thread ID (from search results).
        account: Email or alias — required to identify which account owns this thread.
    """
    return _json(_get_client().read_thread(thread_id, account))


@mcp.tool()
def gmail_download_attachment(
    message_id: str, attachment_id: str, filename: str, account: str,
) -> str:
    """Save an attachment to ~/Downloads/.

    Args:
        message_id: Gmail message ID containing the attachment.
        attachment_id: Attachment ID from gmail_read_message's attachments list.
        filename: Filename to save as (from the attachments list).
        account: Email or alias.
    """
    result = _get_client().download_attachment(message_id, attachment_id, filename, account)
    result["hint"] = _download_hint(filename, result["path"])
    return _json(result)


@mcp.tool()
def gmail_list_drafts(account: str | None = None) -> str:
    """List draft emails.

    Args:
        account: Email or alias. Omit to list drafts from all accounts.
    """
    return _json(_get_client().list_drafts(account))


@mcp.tool()
def gmail_create_draft(
    to: str,
    subject: str,
    body: str,
    account: str,
    cc: str = "",
    bcc: str = "",
    attachments: list[str] | None = None,
) -> str:
    """Create a new draft email.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body (plain text).
        account: Email or alias — required for write operations.
        cc: CC recipients (comma-separated).
        bcc: BCC recipients (comma-separated).
        attachments: List of absolute file paths to attach (PDF, images, videos, any file type).
    """
    return _json(_get_client().create_draft(to, subject, body, account, cc, bcc, attachments))


@mcp.tool()
def gmail_send_message(
    to: str,
    subject: str,
    body: str,
    account: str,
    cc: str = "",
    bcc: str = "",
    reply_to_message_id: str | None = None,
    attachments: list[str] | None = None,
) -> str:
    """Send an email. To reply to a thread, pass reply_to_message_id.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body (plain text).
        account: Email or alias — required for write operations.
        cc: CC recipients (comma-separated).
        bcc: BCC recipients (comma-separated).
        reply_to_message_id: Gmail message ID to reply to. Threads the reply automatically.
        attachments: List of absolute file paths to attach (PDF, images, videos, any file type).
    """
    return _json(_get_client().send_message(to, subject, body, account, cc, bcc, reply_to_message_id, attachments))


@mcp.tool()
def gmail_trash_messages(messages: MessagesList) -> str:
    """STOP: Tell the user what you're about to trash and wait for confirmation. Do NOT call this tool in the same turn as the user's request.

    Trash emails. Supports mixed accounts in ONE call — never split by account.

    Args:
        messages: List of {"id": message_id, "account": alias_or_email}.

    Example — trashing 3 emails from 2 accounts in a single call:
        [{"id": "a1", "account": "personal"}, {"id": "b2", "account": "work"}, {"id": "b3", "account": "work"}]
    """
    return _json(_get_client().trash_messages([m.model_dump() for m in messages]))


@mcp.tool()
def gmail_tag_messages(messages: TagOpList) -> str:
    """STOP: Tell the user what you're about to tag and wait for confirmation. Do NOT call this tool in the same turn as the user's request.

    Add, remove, or swap tags on emails. Each message carries its own tag instructions.

    Each message object has:
    - id: Gmail message ID
    - account: email or alias
    - tag: (optional) tag to add — "important", "credentials", "contacts", or any custom tag
    - remove_tag: (optional) tag to remove

    Examples:
    - Add tag: {"id": "abc", "account": "personal", "tag": "credentials"}
    - Remove tag: {"id": "abc", "account": "personal", "remove_tag": "important"}
    - Swap: {"id": "abc", "account": "personal", "tag": "credentials", "remove_tag": "important"}
    - Mix in one call: different messages can have different tag/remove_tag values.
    """
    return _json(_get_client().tag_messages_batch([m.model_dump() for m in messages]))


@mcp.tool()
def gmail_get_tagged(
    tag: str,
    date: str | None = None,
    account: str | None = None,
) -> str:
    """Get emails by tag. Use for viewing auto-sorted emails (ai/finance, ai/promotions, etc.)
    or built-in tags (important, credentials, contacts).

    Args:
        tag: Tag name — "ai/finance", "important", "credentials", "contacts", or any custom tag.
        date: Date filter — "today", "yesterday", "last_7d", "last_30d". Omit for all time.
        account: Email or alias. Omit to get from all accounts.
    """
    return _json(_get_client().get_tagged(tag, date, account=account))


@mcp.tool()
def gmail_list_tags(account: str | None = None) -> str:
    """List all available tags (built-in and custom).

    Args:
        account: Email or alias. Omit to list tags from all accounts.
    """
    return _json(_get_client().list_tags(account))


@mcp.tool()
def gmail_untrash_message(message_id: str, account: str) -> str:
    """Recover an email from trash.

    Args:
        message_id: The Gmail message ID.
        account: Email or alias — required for write operations.
    """
    return _json(_get_client().untrash_message(message_id, account))


@mcp.tool()
def gmail_list_trash(max_results: int = 50, account: str | None = None) -> str:
    """List emails in trash.

    Args:
        max_results: Maximum number of results (default 50).
        account: Email or alias. Omit to list trash from all accounts.
    """
    return _json(_get_client().list_trash(max_results, account))


@mcp.tool()
def gmail_unsubscribe(message_id: str, account: str) -> str:
    """STOP: Tell the user which email you're about to unsubscribe from and wait for confirmation. Do NOT call this tool in the same turn as the user's request.

    Unsubscribe from a mailing list. Extracts the List-Unsubscribe header and attempts
    HTTP one-click unsubscribe (RFC 8058). Falls back to returning the unsubscribe URL.

    Args:
        message_id: The Gmail message ID (from search results).
        account: Email or alias — required for write operations.
    """
    return _json(_get_client().unsubscribe(message_id, account))


@mcp.tool()
def gmail_delete_tag(tag: str, account: str | None = None) -> str:
    """STOP: Tell the user which tag you're about to delete and wait for confirmation. Do NOT call this tool in the same turn as the user's request.

    Permanently delete a tag (Gmail label). Removes it from all messages that have it.
    Cannot delete "important" (maps to Gmail's STARRED system label).

    Args:
        tag: Tag name to delete (e.g. "credentials", "ai/finance", or any custom tag).
        account: Email or alias. Omit to delete from all accounts.
    """
    return _json(_get_client().delete_tag(tag, account))


@mcp.tool()
def gmail_rename_tag(old_tag: str, new_tag: str, account: str | None = None) -> str:
    """STOP: Tell the user what you're about to rename and wait for confirmation.

    Rename a tag (Gmail label). The ai/ prefix is auto-applied to new_tag for custom tags.
    Cannot rename built-in tags (important, credentials, contacts).

    Args:
        old_tag: Current tag name to rename.
        new_tag: New tag name. ai/ prefix is auto-applied for custom tags.
        account: Email or alias. Omit to rename across all accounts.
    """
    return _json(_get_client().rename_tag(old_tag, _ai_prefix(new_tag), account))


if __name__ == "__main__":
    mcp.run()
