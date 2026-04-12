# WhatsApp AI

Electron app wrapping WhatsApp Web with a built-in MCP server. Replaces the old Puppeteer-based WhatsApp MCP.

Opening the app = MCP server is live on port 39571. No hooks, no separate processes.

## Setup

```bash
cd mcps/whatsapp
npm install
npm run dist
```

First run: scan the QR code with your phone (WhatsApp Settings → Linked Devices). Session persists across restarts.

## Launching

### Option 1: Built .exe (recommended)

Run `dist/win-unpacked/WhatsApp AI.exe`. Pin to taskbar or create a desktop shortcut.

### Option 2: Terminal

```bash
cd mcps/whatsapp && npm start
```

### Rebuilding after code changes

```bash
# Back up caches first
mkdir -p backup-$(date +%Y%m%d) && cp chats.json contacts.json tags.json backup-$(date +%Y%m%d)/ && cp -r messages/ backup-$(date +%Y%m%d)/messages/

npm run dist
```

## MCP config

Claude Code connects to `http://localhost:39571/mcp`:

```json
{
  "mcpServers": {
    "whatsapp": {
      "type": "http",
      "url": "http://localhost:39571/mcp"
    }
  }
}
```

## Tools

Cache-first. Every read tool auto-refreshes its slice of the local cache
from the running WhatsApp app before returning, so callers never need an
explicit sync step.

| Tool | Description |
|------|-------------|
| `whatsapp_list_chats` | List chats/groups by `query` (name/phone substring) and/or `since` (ISO timestamp). Auto-refreshes contacts+chats cache. |
| `whatsapp_list_contacts` | List saved contacts by `query` and/or `tag`. Enriches each contact with chat activity when available. Auto-refreshes contacts+chats cache. |
| `whatsapp_get_messages` | Read messages from a chat by `chat_id`. Incremental sync: skips entirely when `chat.t` hasn't moved; fetches back-history only on a cold chat. Default window: last 48h. |
| `whatsapp_tag_contacts` | Add/remove tags on contacts (name, phone, or id). Default tags: family, work, partner, followup. |

### How sync works

- **Contacts + chats refresh** (`list_chats` / `list_contacts`): iterates the
  WhatsApp Web in-memory Store. Zero network calls to WhatsApp's servers.
- **Message refresh** (`get_messages`): reads `chat.t` from the Store (free)
  and compares against the newest cached message for that chat. If `chat.t`
  hasn't advanced, nothing is fetched. If it has, only messages newer than
  the cached baseline are pulled via `WAWebDBMessageFindLocal.msgFindBefore`
  (local IndexedDB reads, no server calls). Batch size grows exponentially
  (100 → 200 → 400...) until the cached baseline is reached.

### WhatsApp Web API change (April 2026)

WhatsApp Web removed `waitForChatLoading` from the chat message collection
in early April 2026, breaking `ConversationMsgs.loadEarlierMsgs` for all
consumers ([wwebjs/whatsapp-web.js#201706](https://github.com/wwebjs/whatsapp-web.js/issues/201706)).

This project now uses `WAWebDBMessageFindLocal.msgFindBefore` to read
messages from the local IndexedDB instead. This covers all messages
WhatsApp Web has previously downloaded. For very old messages never loaded
in the current session, history is limited to what's in the local DB.

## Inspiration

- [forgexfoundation/whatsapp-desktop-client](https://github.com/forgexfoundation/whatsapp-desktop-client) — Electron shell structure (window state, single-instance lock, protocol handler).
- [pedroslopez/whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js) — Reference for WhatsApp Web webpack module names and Store API patterns. This project does not use whatsapp-web.js as a dependency.
- [wwebjs/whatsapp-web.js#201705](https://github.com/wwebjs/whatsapp-web.js/pull/201705) — `msgFindBefore` fix for the `loadEarlierMsgs` breakage.
