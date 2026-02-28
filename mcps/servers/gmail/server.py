"""Gmail MCP Server — full Gmail control with multi-account support."""

import json
from typing import Annotated

from fastmcp import FastMCP
from pydantic import BaseModel, BeforeValidator

from gmail_client import GmailClient


def _parse_json_str(v):
    """MCP clients may send lists as stringified JSON — parse before validation."""
    if isinstance(v, str):
        return json.loads(v)
    return v


class MessageRef(BaseModel):
    id: str
    account: str


class TagOp(BaseModel):
    id: str
    account: str
    tag: str | None = None
    remove_tag: str | None = None


MessagesList = Annotated[list[MessageRef], BeforeValidator(_parse_json_str)]
TagOpList = Annotated[list[TagOp], BeforeValidator(_parse_json_str)]

mcp = FastMCP(
    "Gmail",
    instructions="""Before executing any write operation (trash, tag, send, create draft), always tell the user exactly what you're about to do and wait for their confirmation.

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
""",
)

_client: GmailClient | None = None


def _get_client() -> GmailClient:
    global _client
    if _client is None:
        _client = GmailClient()
    return _client


def _json(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool()
def gmail_get_profile(account: str | None = None) -> str:
    """Get Gmail account profile info (email, messages total, threads total).

    Args:
        account: Email or alias (e.g. "personal" or "you@gmail.com"). Omit to query all accounts.
    """
    return _json(_get_client().get_profile(account))


@mcp.tool()
def gmail_search_messages(
    query: str | None = None,
    date: str | None = None,
    from_email: str | None = None,
    max_results: int = 200,
    account: str | None = None,
) -> str:
    """Search emails using Gmail query syntax.

    Args:
        query: Raw Gmail query string (e.g. "subject:invoice", "is:unread").
        date: Date shorthand — "today", "last_24h", "yesterday", "last_7d", "last_30d".
              Auto-converted to Gmail query. Can combine with query param.
        from_email: Filter by sender email address.
        max_results: Maximum number of results (default 50).
        account: Email or alias. Omit to search all accounts.
    """
    return _json(_get_client().search_messages(query, date, from_email, max_results, account))


@mcp.tool()
def gmail_read_message(message_id: str, account: str) -> str:
    """Read a specific email by message ID. Returns headers, body, and attachments list.

    Args:
        message_id: The Gmail message ID (from search results).
        account: Email or alias — required to identify which account owns this message.
    """
    return _json(_get_client().read_message(message_id, account))


@mcp.tool()
def gmail_read_thread(thread_id: str, account: str) -> str:
    """Read a full email thread by thread ID. Returns all messages in the thread.

    Args:
        thread_id: The Gmail thread ID (from search results).
        account: Email or alias — required to identify which account owns this thread.
    """
    return _json(_get_client().read_thread(thread_id, account))


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
) -> str:
    """Create a new draft email.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body (plain text).
        account: Email or alias — required for write operations.
        cc: CC recipients (comma-separated).
        bcc: BCC recipients (comma-separated).
    """
    return _json(_get_client().create_draft(to, subject, body, account, cc, bcc))


@mcp.tool()
def gmail_send_message(
    to: str,
    subject: str,
    body: str,
    account: str,
    cc: str = "",
    bcc: str = "",
) -> str:
    """Send an email.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body (plain text).
        account: Email or alias — required for write operations.
        cc: CC recipients (comma-separated).
        bcc: BCC recipients (comma-separated).
    """
    return _json(_get_client().send_message(to, subject, body, account, cc, bcc))


@mcp.tool()
def gmail_trash_message(message_id: str, account: str) -> str:
    """Move an email to trash.

    Args:
        message_id: The Gmail message ID.
        account: Email or alias — required for write operations.
    """
    return _json(_get_client().trash_message(message_id, account))


@mcp.tool()
def gmail_trash_messages(messages: MessagesList) -> str:
    """Trash multiple emails across accounts in a single call.

    Args:
        messages: List of objects with "id" (message ID) and "account" (email or alias).
    """
    return _json(_get_client().trash_messages([m.model_dump() for m in messages]))


@mcp.tool()
def gmail_tag_messages(messages: TagOpList) -> str:
    """Add, remove, or swap tags on emails. Each message carries its own tag instructions.

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
def gmail_get_tagged(tag: str, max_results: int = 50, account: str | None = None) -> str:
    """Get emails by tag. Use "important" for starred, "credentials" for login details, "contacts" for valued relationships, or any custom tag.

    Args:
        tag: Tag name to filter by.
        max_results: Maximum number of results (default 50).
        account: Email or alias. Omit to get from all accounts.
    """
    return _json(_get_client().get_tagged(tag, max_results, account))


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
