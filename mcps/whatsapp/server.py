import json
import logging
import os
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx

_log_dir = Path(__file__).parent / "logs"
_log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[RotatingFileHandler(_log_dir / "beeper.log", maxBytes=5_000_000, backupCount=1)],
)

from fastmcp import FastMCP
from fastmcp.utilities.types import File
from beeper_client import build_client

mcp = FastMCP(
    "Beeper",
    instructions="""IMPORTANT: Always discover a tool's schema with ToolSearch BEFORE calling it for the first time.

To read WhatsApp messages:
1. Call whatsapp_list_chats to find the chat and grab its id.
   - Requires at least one of: query (name/phone substring), tag, or since (ISO timestamp).
2. Pass that id into whatsapp_get_messages to read the conversation.

CRITICAL — whatsapp_get_messages returns pre-formatted conversation output.
You MUST paste the ENTIRE text content into your response as a verbatim code block.
Do NOT summarize, paraphrase, abbreviate, or skip any messages. Show EVERY line.

When whatsapp_download_files returns file content, save each file to ~/Downloads
with its original filename (the token name, e.g. "hash.jpg").""",
)

_client = None
def _get_client():
    global _client
    if _client is None:
        _client = build_client()
    return _client

def _json(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)

def _to_dict(obj):
    if isinstance(obj, list):
        return [_to_dict(x) for x in obj]
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


# ── Tag store (tags.json) ────────────────────────────────────────────

_TAGS_PATH = Path(__file__).parent / "tags.json"

def _read_tags() -> dict:
    with _TAGS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)
        
def _write_tags(data: dict) -> None:
    with _TAGS_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── WhatsApp-flavored tools ──────────────────────────────────────────

def _other_participant(chat: dict) -> dict:
    """Return the non-self participant of a DM (or empty dict)."""
    items = (chat.get("participants") or {}).get("items") or []
    for p in items:
        if not p.get("isSelf"):
            return p
    return {}

def _chat_matches(chat: dict, query: str) -> bool:
    """AND-of-words match on title, ids, and phone."""
    q_words = [w for w in query.lower().split() if w]
    if not q_words:
        return True
    other = _other_participant(chat)
    haystacks = [
        str(chat.get("title") or "").lower(),
        str(chat.get("id") or "").lower(),
        str(other.get("id") or "").lower(),
        str(other.get("fullName") or "").lower(),
        str(other.get("phoneNumber") or "").lower(),
    ]
    return all(any(qw in h for h in haystacks) for qw in q_words)

def _shape_chat(chat: dict, tags: list[str]) -> dict:
    """Project a Beeper Chat into the WhatsApp MCP contact shape."""
    is_group = chat.get("type") == "group"
    other = {} if is_group else _other_participant(chat)
    phone = (other.get("phoneNumber") or "").lstrip("+")
    return {
        "id": chat.get("id"),
        "name": chat.get("title"),
        "number": phone,
        "isGroup": is_group,
        "unreadCount": chat.get("unreadCount"),
        "pinned": chat.get("isPinned"),
        "archived": chat.get("isArchived"),
        "muted": chat.get("isMuted"),
        "lastActivity": chat.get("lastActivity"),
        "preview": chat.get("preview"),
        "tags": tags,
    }


@mcp.tool()
def whatsapp_list_chats(
    query: str | None = None,
    tag: str | None = None,
    since: str | None = None,
) -> str:
    """List WhatsApp chats (DMs + groups). At least one of `query`, `tag`, or `since` is required.
      • query  — substring match on chat title, id, contact name, or phone
      • tag    — filter by tag (e.g. family, work, partner, followup)
      • since  — ISO datetime; chats with lastActivity at or after this time

    Each result includes its tags. Pass a result's id into whatsapp_get_messages
    to read the conversation.

    Default tags: family, work, partner, followup. Custom tags are auto-created
    on first use via whatsapp_tag_contacts.
    """
    if not query and not tag and not since:
        return "Pass at least one of `query`, `tag`, or `since`."

    client = _get_client()
    contact_tags = _read_tags().get("contacts", {})

    chats = [_to_dict(c) for c in client.chats.list(account_ids=["whatsapp"])]

    if query:
        chats = [c for c in chats if _chat_matches(c, query)]
    if tag:
        chats = [c for c in chats if tag in contact_tags.get(c.get("id") or "", [])]
    if since:
        chats = [c for c in chats if (c.get("lastActivity") or "") >= since]

    shaped = [_shape_chat(c, contact_tags.get(c.get("id") or "", [])) for c in chats]
    return _json(shaped)


_MEDIA_LABELS = {
    "IMAGE": "📷  Photo",
    "VIDEO": "🎥  Video",
    "VOICE": "🎤  Voice note",
    "AUDIO": "🎵  Audio",
    "FILE": "📎  File",
    "STICKER": "💬  Sticker",
    "LOCATION": "📍  Location",
    "REACTION": "👍  Reaction",
    "NOTICE": "ℹ️",
}
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"]

def _parse_ts(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


# ── Media prefix (cached once per process) ───────────────────────────

_MEDIA_PREFIX: str | None = None  # e.g. "mxc://local.beeper.com/doasfrancisco_"

def _get_media_prefix() -> str:
    global _MEDIA_PREFIX
    if _MEDIA_PREFIX is None:
        accts = _get_client().accounts.list()
        matrix = next((a for a in accts if a.network == "Beeper (Matrix)"), None)
        if not matrix:
            raise RuntimeError("Beeper (Matrix) account not found in accounts.list()")
        user_id = matrix.user.id  # "@doasfrancisco:beeper.com"
        username = user_id.lstrip("@").split(":")[0]
        _MEDIA_PREFIX = f"mxc://local.beeper.com/{username}_"
    return _MEDIA_PREFIX

def _strip_prefix(mxc_id: str) -> str:
    """mxc://local.beeper.com/doasfrancisco_<hash> → <hash>. Fallback: return as-is."""
    if not mxc_id:
        return ""
    try:
        prefix = _get_media_prefix()
        if mxc_id.startswith(prefix):
            return mxc_id[len(prefix):]
    except Exception:
        pass
    return mxc_id

def _format_messages(messages: list[dict]) -> str:
    messages = sorted(messages, key=lambda m: _parse_ts(m.get("timestamp")))
    lines: list[str] = []
    last_date = ""
    for m in messages:
        dt = _parse_ts(m.get("timestamp")).astimezone()
        date_key = dt.strftime("%Y-%m-%d")
        if date_key != last_date:
            last_date = date_key
            if lines:
                lines.append("")
            lines.append(f"-- {_DAY_NAMES[dt.weekday()]}, {_MONTH_NAMES[dt.month - 1]} {dt.day} --")

        hour12 = dt.hour % 12 or 12
        ampm = "PM" if dt.hour >= 12 else "AM"
        time = f"{hour12}:{dt.minute:02d} {ampm}"

        sender = "< You" if m.get("isSender") else f"> {m.get('senderName') or m.get('senderID') or ''}"

        caption = m.get("text") or ""
        mtype = m.get("type")
        label = _MEDIA_LABELS.get(mtype)

        if label and mtype != "TEXT":
            atts = m.get("attachments") or []
            att = atts[0] if atts else None
            token_part = ""
            if att:
                hash_part = _strip_prefix(att.get("id") or "")
                ext = Path(att.get("fileName") or "").suffix
                if hash_part:
                    token_part = f" [{hash_part}{ext}]"
            caption_part = f" ({caption})" if caption else ""
            body = f"{label}{token_part}{caption_part}"
        else:
            body = caption

        lines.append(f"{sender} ({time}) -- {body}")
    return "\n".join(lines)


@mcp.tool()
def whatsapp_get_messages(chat_id: str, since: str | None = None) -> str:
    """Read messages from a WhatsApp chat (DM or group) by chat_id.

      • chat_id — Matrix room id from whatsapp_list_chats (e.g. "!abc:beeper.local")
      • since   — ISO datetime; only messages at or after this time. Default: 48h ago.

    Returns pre-formatted conversation output — paste the entire block verbatim.
    Do NOT summarize, paraphrase, abbreviate, or skip any messages.
    """
    if not since:
        since = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

    client = _get_client()
    messages = [_to_dict(m) for m in client.messages.search(chat_ids=[chat_id], date_after=since)]
    if not messages:
        return f"No messages in the requested window (since {since})."

    formatted = _format_messages(messages)
    return f"[VERBATIM — paste this entire block into your response. Do NOT summarize or skip lines.]\n\n{formatted}"


@mcp.tool()
def whatsapp_tag_contacts(entries: list[dict]) -> str:
    """Add or remove tags on one or more WhatsApp chats (DMs or groups) in a single call.

    Each entry: {chat_id, tags, action}.
      • chat_id — Matrix room id from whatsapp_list_chats (e.g. "!abc:beeper.local")
      • tags    — list of tag names (e.g. ["family", "followup"])
      • action  — "add" (default) or "remove"

    Custom tags are auto-created with an empty description on first use.
    Default tags: family, work, partner, followup.
    """
    data = _read_tags()
    tags_map = data.setdefault("tags", {})
    contact_tags = data.setdefault("contacts", {})
    lines = []

    for entry in entries:
        chat_id = entry.get("chat_id")
        tags = entry.get("tags") or []
        action = entry.get("action", "add")

        if not chat_id or not tags:
            lines.append(f'"{chat_id}": missing chat_id or tags')
            continue

        current = set(contact_tags.get(chat_id, []))
        if action == "remove":
            current.difference_update(tags)
        else:
            for t in tags:
                tags_map.setdefault(t, {"description": ""})
            current.update(tags)

        if current:
            contact_tags[chat_id] = sorted(current)
        else:
            contact_tags.pop(chat_id, None)

        lines.append(f'"{chat_id}": [{", ".join(sorted(current))}]')

    _write_tags(data)
    return "\n".join(lines)


_BEEPER_BASE = os.getenv("BEEPER_BASE_URL", "http://localhost:23373")
_BEEPER_TOKEN = os.getenv("BEEPER_ACCESS_TOKEN", "")


@mcp.tool()
def whatsapp_download_files(tokens: list[str]) -> list:
    """Download attachments shown as [token] in whatsapp_get_messages output.

      • tokens — list of hash tokens (e.g. "hash.jpg") from get_messages

    Streams file bytes from Beeper's serve endpoint and returns them directly
    to the client. No files are saved on the server.
    """
    prefix = _get_media_prefix()
    results = []

    for t in tokens:
        if not t:
            results.append("ERROR: empty token")
            continue

        is_raw_url = t.startswith(("mxc://", "localmxc://"))
        if is_raw_url:
            mxc_url = t
            name = t.split("/")[-1]
        else:
            p = Path(t)
            hash_part, ext = p.stem, p.suffix
            mxc_url = f"{prefix}{hash_part}"
            name = t

        try:
            resp = httpx.get(
                f"{_BEEPER_BASE}/v1/assets/serve",
                params={"url": mxc_url},
                headers={"Authorization": f"Bearer {_BEEPER_TOKEN}", "Accept": "*/*"},
                timeout=60,
            )
            resp.raise_for_status()
            fmt = Path(name).suffix.lstrip(".") or "bin"
            results.append(File(data=resp.content, format=fmt, name=name))
        except Exception as e:
            results.append(f"ERROR ({t}): {type(e).__name__}: {str(e)[:120]}")

    return results


if __name__ == "__main__":
    mcp.run()
