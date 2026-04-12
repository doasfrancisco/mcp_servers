/**
 * mcp-server.js — MCP HTTP server running inside Electron's main process.
 *
 * Every read tool auto-refreshes its cache slice from the renderer before
 * returning. Contacts+chats refresh is free (Store iteration). Message
 * refresh is incremental (skipped when chat.t hasn't moved). The one branch
 * that triggers real WhatsApp server requests is get_messages on a cold
 * chat, where inject.js loops loadEarlierMsgs.
 *
 * IPC flow:
 *   tool handler → callRenderer → IPC → inject.js → Store API → IPC → cache merge
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest } from "@modelcontextprotocol/sdk/types.js";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import express from "express";
import cors from "cors";
import { z } from "zod";
import { app, ipcMain } from "electron";
import * as cache from "./cache.js";

const ICON_B64 = readFileSync(join(app.getAppPath(), "icon_48x48.png")).toString("base64");

const PORT = 39571;

// ── Renderer bridge ───────────────────────────────────────────

const pendingRequests = new Map();
let nextRequestId = 1;

let _getWindow = null;
let _isReady = null;

export function setBridge(getWindowFn, isReadyFn) {
  _getWindow = getWindowFn;
  _isReady = isReadyFn;
}

ipcMain.handle("wa:response", (_event, requestId, result, error) => {
  const pending = pendingRequests.get(requestId);
  if (!pending) return;
  pendingRequests.delete(requestId);
  if (error) pending.reject(new Error(error));
  else pending.resolve(result);
});

function callRenderer(method, args = []) {
  const win = _getWindow?.();
  if (!win) return Promise.reject(new Error("WhatsApp window not open"));
  if (!_isReady?.()) return Promise.reject(new Error("WhatsApp is still loading — try again in ~15 seconds"));

  const requestId = nextRequestId++;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingRequests.delete(requestId);
      reject(new Error("Renderer call timed out (15s)"));
    }, 15000);

    pendingRequests.set(requestId, {
      resolve: (result) => { clearTimeout(timeout); resolve(result); },
      reject: (err) => { clearTimeout(timeout); reject(err); },
    });

    win.webContents.send("wa:request", requestId, method, args);
  });
}

// ── Auto-sync helpers ────────────────────────────────────────

async function autoSyncContactsChats() {
  const [contacts, chats] = await Promise.all([
    callRenderer("getContacts"),
    callRenderer("getChats"),
  ]);
  cache.mergeContacts(contacts);
  cache.mergeChats(chats);
}

function resolveSenderNames(messages) {
  const mentionMap = cache.getMentionMap();
  for (const m of messages) {
    const num = (m.from || "").split("@")[0];
    if (num && mentionMap[num]) m.sender = mentionMap[num];
  }
}

async function fetchMessagesUntil(chatId, stopAt) {
  const all = await callRenderer("getMessagesUntil", [chatId, stopAt]);
  return stopAt ? all.filter((m) => m.timestamp > stopAt) : all;
}

async function autoSyncMessages(chatId, since) {
  const newestCached = cache.getNewestCachedMessageTimestamp(chatId);

  let fresh;
  if (!newestCached) {
    fresh = await fetchMessagesUntil(chatId, since);
  } else {
    const chatTimestamp = cache.getCachedChatTimestamp(chatId);
    if (chatTimestamp && chatTimestamp <= newestCached) return;
    fresh = await fetchMessagesUntil(chatId, newestCached);
  }

  if (!fresh || fresh.length === 0) return;
  resolveSenderNames(fresh);
  cache.mergeMessages(chatId, fresh);
}

// ── Message formatter ─────────────────────────────────────────

const MEDIA_LABELS = {
  image: "[image]", video: "[video]", audio: "[audio]",
  ptt: "[voice note]", document: "[document]", sticker: "[sticker]",
  call_log: "[call]", vcard: "[contact]", location: "[location]",
};

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function toLocalTime(utcISO) {
  if (!utcISO) return null;
  const dt = new Date(utcISO);
  const h = dt.getHours();
  const m = dt.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  const month = MONTH_NAMES[dt.getMonth()];
  const day = dt.getDate();
  return `${month} ${day}, ${h12}:${m} ${ampm}`;
}

function localizeResults(results) {
  return results.map((r) => {
    const out = { ...r };
    if (out.timestamp) out.timestamp = toLocalTime(out.timestamp);
    if (out.lastMessage?.timestamp) {
      out.lastMessage = { ...out.lastMessage, timestamp: toLocalTime(out.lastMessage.timestamp) };
    }
    return out;
  });
}

function formatMessages(messages, chatName, mentionMap = {}) {
  const lines = [];
  let lastDate = "";

  for (const m of messages) {
    const dt = new Date(m.timestamp);
    const dateKey = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;

    if (dateKey !== lastDate) {
      lastDate = dateKey;
      const dayName = DAY_NAMES[dt.getDay()];
      const month = MONTH_NAMES[dt.getMonth()];
      const day = dt.getDate();
      if (lines.length > 0) lines.push("");
      lines.push(`-- ${dayName}, ${month} ${day} --`);
    }

    if (m.type === "pinned_message") continue;

    const hours = dt.getHours();
    const mins = dt.getMinutes().toString().padStart(2, "0");
    const ampm = hours >= 12 ? "PM" : "AM";
    const h12 = hours % 12 || 12;
    const time = `${h12}:${mins} ${ampm}`;

    const fromMe = m.id.startsWith("true_");
    const sender = fromMe ? "< You" : `> ${m.sender || chatName}`;

    let body = m.body || "";
    const label = MEDIA_LABELS[m.type];
    if (label && m.type !== "chat") {
      if (m.type === "document" && body) body = `[${body}]`;
      else body = body ? `${label} ${body}` : label;
    }

    body = body.replace(/@(\d{5,})/g, (match, num) => {
      const name = mentionMap[num];
      return name ? `@${name}` : match;
    });

    lines.push(`${sender} (${time}) -- ${body}`);
  }

  return lines.join("\n");
}

// ── MCP server factory ───────────────────────────────────────

function createServer() {
  const server = new McpServer({
    name: "whatsapp",
    version: "3.0.0",
    icons: [{
      src: `data:image/png;base64,${ICON_B64}`,
      mimeType: "image/png",
      sizes: ["48x48"],
    }],
    instructions: `To read WhatsApp messages:
1. Call whatsapp_list_chats (or whatsapp_list_contacts) to find the chat and grab its id.
   - whatsapp_list_chats requires at least one of: query (name/phone substring) or since (ISO timestamp).
   - whatsapp_list_contacts requires at least one of: query or tag.
2. Pass that id into whatsapp_get_messages to read the conversation.

Every read tool auto-refreshes its slice of the cache from the WhatsApp app —
you never need to call a separate sync step.

CRITICAL — whatsapp_get_messages returns pre-formatted conversation output.
You MUST paste the ENTIRE text content into your response as a verbatim code block.
Do NOT summarize, paraphrase, abbreviate, or skip any messages. Show EVERY line.`,
  });

  // ── whatsapp_list_chats ──────────────────────────────────

  server.tool(
    "whatsapp_list_chats",
    `List WhatsApp chats and groups. At least one of \`query\` or \`since\` is required.
  • query  — substring match on chat name, id, or phone number
  • since  — ISO timestamp; returns chats with activity at or after this time

Auto-refreshes the contacts and chats caches from the WhatsApp app before
querying (free — iterates the in-memory Store, no server calls).

Returns each match with id, name, timestamp, unreadCount, archive/pin state,
last message, and participants (groups). Pass the id into
whatsapp_get_messages to read the conversation.`,
    {
      query: z.string().optional().describe("Name, id, or phone substring to search for"),
      since: z.string().optional().describe("ISO datetime — chats with activity at or after this timestamp"),
    },
    async ({ query, since }) => {
      if (!query && !since) {
        return { content: [{ type: "text", text: "Pass at least one of `query` or `since`." }], isError: true };
      }
      let warning = null;
      try {
        await autoSyncContactsChats();
      } catch (err) {
        warning = `Auto-sync failed (${err.message}) — serving cached data.`;
      }
      try {
        const results = cache.listChatsFiltered({ query, since });
        const body = JSON.stringify(localizeResults(results), null, 2);
        const text = warning ? `${warning}\n\n${body}` : body;
        return { content: [{ type: "text", text }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── whatsapp_list_contacts ───────────────────────────────

  server.tool(
    "whatsapp_list_contacts",
    `List saved WhatsApp contacts. At least one of \`query\` or \`tag\` is required.
  • query  — substring match on contact name, pushname, or phone number
  • tag    — filter by tag (e.g. family, work, partner, followup)

Auto-refreshes the contacts and chats caches from the WhatsApp app before
querying (free — iterates the in-memory Store, no server calls).

Each result includes its tags and — when the contact has an active chat —
chat activity fields (timestamp, unreadCount, archived, pinned, lastMessage).
Pass a contact's id into whatsapp_get_messages to read the conversation.

Default tags: family, work, partner, followup. Custom tags are auto-created
on first use via whatsapp_tag_contacts.`,
    {
      query: z.string().optional().describe("Name, pushname, or phone substring"),
      tag: z.string().optional().describe("Tag name (family, work, partner, followup, or any custom)"),
    },
    async ({ query, tag }) => {
      if (!query && !tag) {
        return { content: [{ type: "text", text: "Pass at least one of `query` or `tag`." }], isError: true };
      }
      let warning = null;
      try {
        await autoSyncContactsChats();
      } catch (err) {
        warning = `Auto-sync failed (${err.message}) — serving cached data.`;
      }
      try {
        const results = cache.listContactsFiltered({ query, tag });
        const body = JSON.stringify(localizeResults(results), null, 2);
        const text = warning ? `${warning}\n\n${body}` : body;
        return { content: [{ type: "text", text }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── whatsapp_get_messages ────────────────────────────────

  server.tool(
    "whatsapp_get_messages",
    `Read messages from a specific WhatsApp chat by id.
Pass the chat_id returned by whatsapp_list_chats or whatsapp_list_contacts.

Auto-sync behavior:
  • Cold chat (no cached messages)      → fetches everything available.
    This is the one branch that triggers real WhatsApp server requests;
    capped at ~5000 messages of back-history per call.
  • Warm chat with new activity          → incrementally fetches only the
    messages added since the newest cached one.
  • Warm chat with no new activity       → zero network calls, cache only.

Default window: last 48 hours. Use \`since\` (ISO datetime) for a different cutoff.

Output is pre-formatted — paste the entire block verbatim. Do NOT summarize,
paraphrase, abbreviate, or skip any messages. Show EVERY line.`,
    {
      chat_id: z.string().describe("Chat id from list_chats / list_contacts (e.g. '1234@c.us' or '1234@g.us')"),
      since: z.string().optional().describe("ISO datetime — only return messages at or after this time. Default: 48h ago."),
    },
    async ({ chat_id, since }) => {
      let warning = null;
      try {
        await autoSyncContactsChats();
        const syncCutoff = since || new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
        await autoSyncMessages(chat_id, syncCutoff);
      } catch (err) {
        warning = `Auto-sync failed (${err.message}) — serving cached messages only.`;
      }
      try {
        const messages = cache.readCachedMessages(chat_id, since);
        const chatName = cache.getCachedChatName(chat_id);

        if (messages.length === 0) {
          const empty = `No messages cached for "${chatName}" in the requested window.`;
          return { content: [{ type: "text", text: warning ? `${warning}\n${empty}` : empty }] };
        }

        const mentionMap = cache.getMentionMap();
        const formatted = formatMessages(messages, chatName, mentionMap);
        const header = warning ? `${warning}\n\n` : "";
        const output = `${header}[VERBATIM — paste this entire block into your response. Do NOT summarize or skip lines.]\n\n${formatted}`;
        return { content: [{ type: "text", text: output, annotations: { audience: ["user"], priority: 1.0 } }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── whatsapp_tag_contacts ────────────────────────────────

  server.tool(
    "whatsapp_tag_contacts",
    `Add or remove tags on one or more WhatsApp contacts in a single call.
Each entry specifies a contact, the tags, and whether to add or remove.
Contacts can be referenced by name, phone number, or the id returned by
whatsapp_list_contacts — the cache is already up to date from the last
list call, no separate sync needed.

Default tags: family, work, partner, followup. Custom tags are auto-created
when first used.
If a contact is not found but candidates exist, all possible matches are
listed — present every candidate to the user and ask which one they meant
before retrying.`,
    {
      entries: z.array(z.object({
        contact: z.string().describe("Contact or group name, phone number, or id"),
        tags: z.array(z.string()).describe('Tag names (e.g. ["family", "followup"])'),
        action: z.enum(["add", "remove"]).default("add").describe('"add" (default) or "remove"'),
      })).describe("List of { contact, tags, action } entries to process"),
    },
    async ({ entries }) => {
      const lines = [];
      for (const { contact, tags, action = "add" } of entries) {
        try {
          const result = action === "remove"
            ? cache.untagContact(contact, tags)
            : cache.tagContact(contact, tags);
          if (result.error) lines.push(`"${contact}": ${result.error}`);
          else if (result.candidates) lines.push(`"${contact}": not found. Did you mean: ${result.candidates.join(", ")}?`);
          else lines.push(`"${result.contact}": [${result.tags.join(", ")}]`);
        } catch (err) {
          lines.push(`"${contact}": Error — ${err.message}`);
        }
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    }
  );

  return server;
}

// ── Express HTTP server ───────────────────────────────────────

export async function startMcpServer() {
  const app = express();
  app.use(cors());
  app.use(express.json());

  const transports = {};

  app.post("/mcp", async (req, res) => {
    const sessionId = req.headers["mcp-session-id"];
    try {
      if (sessionId && transports[sessionId]) {
        await transports[sessionId].transport.handleRequest(req, res, req.body);
        return;
      }
      if (isInitializeRequest(req.body)) {
        const transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (sid) => {
            console.error(`[whatsapp-mcp] Session initialized: ${sid}`);
            transports[sid] = { transport, server };
          },
        });
        transport.onclose = () => {
          const sid = transport.sessionId;
          if (sid) delete transports[sid];
        };
        const server = createServer();
        await server.connect(transport);
        await transport.handleRequest(req, res, req.body);
        return;
      }
      // Stale session — auto-create
      if (sessionId) {
        console.error(`[whatsapp-mcp] Stale session ${sessionId}, auto-creating`);
        const transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => sessionId,
        });
        transport.onclose = () => { delete transports[sessionId]; };
        const server = createServer();
        await server.connect(transport);
        const inner = transport._webStandardTransport;
        inner._initialized = true;
        inner.sessionId = sessionId;
        transports[sessionId] = { transport, server };
        await transport.handleRequest(req, res, req.body);
        return;
      }
      res.status(400).json({ jsonrpc: "2.0", error: { code: -32000, message: "Bad Request: No valid session ID" }, id: null });
    } catch (err) {
      console.error("[whatsapp-mcp] HTTP error:", err);
      if (!res.headersSent) res.status(500).json({ jsonrpc: "2.0", error: { code: -32603, message: "Internal server error" }, id: null });
    }
  });

  app.get("/mcp", async (req, res) => {
    const sessionId = req.headers["mcp-session-id"];
    if (!sessionId || !transports[sessionId]) return res.status(400).send("Invalid or missing session ID");
    await transports[sessionId].transport.handleRequest(req, res);
  });

  app.delete("/mcp", async (req, res) => {
    const sessionId = req.headers["mcp-session-id"];
    if (!sessionId || !transports[sessionId]) return res.status(400).send("Invalid or missing session ID");
    try {
      await transports[sessionId].transport.close();
      delete transports[sessionId];
      res.status(200).send("Session terminated");
    } catch {
      res.status(500).send("Error terminating session");
    }
  });

  app.get("/health", (_req, res) => res.send("ok"));

  return new Promise((resolve) => {
    app.listen(PORT, () => {
      console.error(`[whatsapp-mcp] MCP server running on http://localhost:${PORT}/mcp`);
      resolve();
    });
  });
}
