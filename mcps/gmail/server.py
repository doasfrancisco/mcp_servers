"""Gmail MCP Server — full Gmail control with multi-account support."""

import json
import webbrowser
from contextlib import asynccontextmanager
from typing import Annotated

from fastmcp import FastMCP
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
- gmail_search_messages automatically skips ai/* emails by default and returns their counts in "ai_skipped".
- Always show the ai_skipped summary to the user (e.g. "Also sorted: ai/programming (1), ai/finance (3)").
- When the user asks to "show all" or explicitly wants auto-sorted emails, set skip_ai=false.
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


@mcp.tool()
def gmail_search_messages(
    query: str | None = None,
    date: str | None = None,
    from_email: str | None = None,
    max_results: int = 200,
    account: str | None = None,
    skip_ai: bool = True,
) -> str:
    """Search emails using Gmail query syntax.

    By default, emails with ai/* tags are excluded from results and their counts
    are returned in "ai_skipped". Set skip_ai=false to include everything.

    Args:
        query: Raw Gmail query string (e.g. "subject:invoice", "is:unread").
        date: Date shorthand — "today", "last_24h", "yesterday", "last_7d", "last_30d".
              Auto-converted to Gmail query. Can combine with query param.
        from_email: Filter by sender email address.
        max_results: Maximum number of results (default 50).
        account: Email or alias. Omit to search all accounts.
        skip_ai: Exclude ai/* tagged emails from results (default true). Their counts are returned in ai_skipped.
    """
    return _json(_get_client().search_messages(query, date, from_email, max_results, account, skip_ai))


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
    reply_to_message_id: str | None = None,
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
    """
    return _json(_get_client().send_message(to, subject, body, account, cc, bcc, reply_to_message_id))


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
