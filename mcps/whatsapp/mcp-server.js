/**
 * mcp-server.js — MCP HTTP server running inside Electron's main process.
 *
 * Same Express + StreamableHTTPServerTransport pattern as the old server.js.
 * Same port (39571), same tool schemas — Claude Code config doesn't change.
 *
 * Data flow for sync tools:
 *   MCP tool handler → callRenderer(method, args) → IPC → inject.js → Store API
 *   inject.js → IPC → main process → cache merge → MCP response
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest } from "@modelcontextprotocol/sdk/types.js";
import { randomUUID } from "node:crypto";
import express from "express";
import cors from "cors";
import { z } from "zod";
import { ipcMain } from "electron";
import * as cache from "./cache.js";

const PORT = 39571;

// ── Renderer bridge ───────────────────────────────────────────
// Calls inject.js functions in the WhatsApp Web page via IPC.
// The main process sends a request, preload forwards it as a window event,
// inject.js handles it and posts the result back.

const pendingRequests = new Map();
let nextRequestId = 1;

// Reference to main window — set by main.js after window creation
let _getWindow = null;
let _isReady = null;

/** Called by main.js to register the window accessor. */
export function setBridge(getWindowFn, isReadyFn) {
  _getWindow = getWindowFn;
  _isReady = isReadyFn;
}

// Handle responses from the renderer
ipcMain.handle("wa:response", (_event, requestId, result, error) => {
  const pending = pendingRequests.get(requestId);
  if (!pending) return;
  pendingRequests.delete(requestId);
  if (error) pending.reject(new Error(error));
  else pending.resolve(result);
});

/**
 * Call a method on window.__waAPI in the renderer process.
 * Returns a promise that resolves with the result.
 */
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

// ── Message formatter ─────────────────────────────────────────

const MEDIA_LABELS = {
  image: "[image]", video: "[video]", audio: "[audio]",
  ptt: "[voice note]", document: "[document]", sticker: "[sticker]",
  call_log: "[call]", vcard: "[contact]",
};

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Convert a UTC ISO string to local timezone display string. */
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

/** Convert timestamps in find results to local timezone for display. */
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
      else if (m.type === "image" || m.type === "video" || m.type === "sticker") body = label;
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

const RELATIONSHIP_TAGS = {
  girlfriend: "partner", boyfriend: "partner", wife: "partner", husband: "partner",
  partner: "partner", spouse: "partner", fiance: "partner", fiancee: "partner",
  coworker: "work", colleague: "work", boss: "work",
  brother: "family", sister: "family", mom: "family", dad: "family",
  mother: "family", father: "family", cousin: "family", uncle: "family", aunt: "family",
};

function createServer() {
  const server = new McpServer({
    name: "whatsapp",
    version: "2.0.0",
    instructions: `When asked to show messages:
1. If you don't have an exact contact name, use whatsapp_find to resolve it first.
2. Try whatsapp_get_messages — it reads from local cache with zero API calls.
3. Only if the cache is empty, ask the user before syncing.

CRITICAL — whatsapp_get_messages returns pre-formatted conversation output.
You MUST paste the ENTIRE text content into your response as a verbatim code block.
Do NOT summarize, paraphrase, abbreviate, or skip any messages. Show EVERY line.`,
  });

  // ── whatsapp_sync ─────────────────────────────────────────

  server.tool(
    "whatsapp_sync",
    `Sync WhatsApp data from the app into the local cache.
NEVER call this to read messages — use whatsapp_get_messages first.
Only sync messages if whatsapp_get_messages returned empty and the user agreed to sync.
This is the ONLY tool that makes API calls — all other tools read from cache.
With no params: syncs contacts and chats in parallel.
With what="messages" + chats array: fetches and caches messages for specific chats.
Returns stats on what was synced.`,
    {
      what: z.enum(["messages"]).optional().describe('Optional: "messages" to sync messages for specific chats. Omit to sync contacts+chats.'),
      chats: z.array(z.string()).optional().describe('Chat names to sync messages for (required when what="messages")'),
      since: z.string().optional().describe("ISO date (YYYY-MM-DD) — sync messages from this date. Default: 2 days ago."),
    },
    async ({ what, chats: chatNames, since }) => {
      try {
        if (what === "messages") {
          if (!chatNames || chatNames.length === 0) {
            return { content: [{ type: "text", text: "Provide a chats array with chat names to sync messages for." }] };
          }

          const cutoff = since
            ? new Date(since + "T00:00:00Z")
            : new Date(Date.now() - 2 * 24 * 60 * 60 * 1000);
          const cutoffISO = cutoff.toISOString();

          const results = [];
          for (const name of chatNames) {
            // Resolve via chats cache first (has @lid IDs that Chat store recognizes),
            // then fall back to contacts cache (has @c.us IDs).
            // This mirrors the old whatsapp-web.js findChat() approach.
            const resolved = cache.resolveChatByName(name) || cache.resolveContact(name);
            if (!resolved) {
              results.push({ chat: name, error: "not found" });
              continue;
            }

            // Fetch in growing batches until we've reached past the cutoff date
            // (same approach as old whatsapp-web.js syncMessages)
            let messages = [];
            let batch = 50;
            const MAX_BATCH = 1000;
            while (batch <= MAX_BATCH) {
              messages = await callRenderer("getMessages", [resolved.id, batch]);
              if (messages.length === 0 || messages.length < batch) break;
              // messages[0] is the oldest (chronological order)
              if (messages[0].timestamp <= cutoffISO) break;
              batch *= 2;
            }

            // Resolve sender names to address book names (same as legacy).
            // inject.js returns pushnames from senderObj; mentionMap has address book names.
            const mentionMap = cache.getMentionMap();
            for (const m of messages) {
              const num = (m.from || "").split("@")[0];
              if (num && mentionMap[num]) m.sender = mentionMap[num];
            }

            const filtered = messages.filter((m) => m.timestamp >= cutoffISO);
            const mergeResult = cache.mergeMessages(resolved.id, filtered);
            results.push({ chat: resolved.name, id: resolved.id, synced: filtered.length, ...mergeResult });
          }
          return { content: [{ type: "text", text: JSON.stringify(results, null, 2) }] };
        }

        // Default: sync contacts + chats from WhatsApp Store
        const [contacts, chats] = await Promise.all([
          callRenderer("getContacts"),
          callRenderer("getChats"),
        ]);

        const contactsResult = cache.mergeContacts(contacts);
        const chatsResult = cache.mergeChats(chats);

        let text = `Contacts: ${contactsResult.synced} total, ${contactsResult.added} new, ${contactsResult.changed} changed.\nChats: ${chatsResult.synced} total, ${chatsResult.added} new, ${chatsResult.changed} changed, ${chatsResult.updated} updated.`;
        if (chatsResult.updatedChats.length > 0) {
          text += `\n\nUpdated chats:\n${JSON.stringify(chatsResult.updatedChats, null, 2)}`;
        }
        return { content: [{ type: "text", text }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── whatsapp_find ─────────────────────────────────────────

  server.tool(
    "whatsapp_find",
    `Find people, groups, or chats by name, tag, date, or filter.
Searches both contacts and chats caches in a single merged view — contacts provide
identity (name, number), chats provide activity (last message, unread count, timestamps).
Never calls the API — use whatsapp_sync first if caches are empty.
Each result includes its tags array.
Default tags: family, work, partner, followup. Custom tags are auto-created when first used.
When the user refers to someone by relationship (e.g. girlfriend, wife, coworker, brother), search by the matching tag — not by name.
When no params are given, defaults to today's activity only.`,
    {
      query: z.string().optional().describe("Name or phone number to search for"),
      tag: z.string().optional().describe("Filter by tag (e.g. family, work, partner, followup)"),
      from: z.string().optional().describe("ISO date (YYYY-MM-DD) — entries with activity on or after this date"),
      filter: z.enum(["pinned", "unread", "groups"]).optional().describe("Filter: pinned, unread, or groups only"),
    },
    async ({ query, tag, from, filter }) => {
      try {
        let results = cache.find({ query, tag, from, filter });

        if (results.length === 0 && query && !tag) {
          const mapped = RELATIONSHIP_TAGS[query.toLowerCase()];
          if (mapped) {
            results = cache.find({ tag: mapped, from, filter });
            if (results.length > 0) {
              return { content: [{ type: "text", text: `No contact named "${query}", but found results via the "${mapped}" tag:\n${JSON.stringify(localizeResults(results), null, 2)}` }] };
            }
          }
        }

        if (results.length === 0) {
          const reason = tag ? `No results found with tag "${tag}".`
            : query ? `No results found matching "${query}".`
            : "No results found. The cache may be empty — use whatsapp_sync first.";
          return { content: [{ type: "text", text: reason }] };
        }
        return { content: [{ type: "text", text: JSON.stringify(localizeResults(results), null, 2) }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── whatsapp_get_messages ─────────────────────────────────

  server.tool(
    "whatsapp_get_messages",
    `ALWAYS call this FIRST when the user asks for messages — before syncing.
This reads from the local cache with zero API calls.
If you don't have an exact contact name, use whatsapp_find to resolve it first.
If the cache is empty, tell the user and offer to sync — do NOT auto-sync.
Output is pre-formatted — show it directly to the user WITHOUT reformatting or summarizing.
NEVER summarize, paraphrase, or skip messages. Show the FULL output as-is.`,
    {
      chat: z.string().describe("Contact name, group name, or phone number"),
      since: z.string().optional().describe("ISO date (YYYY-MM-DD) — only return messages from this date onward. Default: last 24h."),
    },
    async ({ chat: query, since }) => {
      try {
        const result = cache.getMessages(query, since);
        if (result.error) return { content: [{ type: "text", text: result.error }] };
        if (result.messages.length === 0) {
          return { content: [{ type: "text", text: `No messages found for "${result.chat}". Want me to sync?` }] };
        }
        const mentionMap = cache.getMentionMap();
        const formatted = formatMessages(result.messages, result.chat, mentionMap);
        const output = `[VERBATIM — paste this entire block into your response. Do NOT summarize or skip lines.]\n\n${formatted}`;
        return { content: [{ type: "text", text: output, annotations: { audience: ["user"], priority: 1.0 } }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── whatsapp_tag_contacts ─────────────────────────────────

  server.tool(
    "whatsapp_tag_contacts",
    `Add or remove tags from one or more WhatsApp contacts in a single call.
Each entry specifies a contact, the tags, and whether to add or remove.
Looks up each contact by name or phone number in the local cache — sync contacts first if needed.
Default tags: family, work, partner, followup. Custom tags are auto-created when first used.
If a contact is not found but candidates exist, all possible matches are listed —
present every candidate to the user and ask which one they meant before retrying.`,
    {
      entries: z.array(z.object({
        contact: z.string().describe("Contact or group name, or phone number"),
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

  // ── whatsapp_send (NEW) ───────────────────────────────────

  server.tool(
    "whatsapp_send",
    `Send a text message to a WhatsApp contact or group.
Resolves the contact name to an ID from the local cache, then sends via WhatsApp Web.
This is safe — it uses the official WhatsApp Web interface, not an unofficial API.
Always confirm with the user before sending.`,
    {
      chat: z.string().describe("Contact name, group name, or phone number"),
      message: z.string().describe("Text message to send"),
    },
    async ({ chat: query, message }) => {
      try {
        const resolved = cache.resolveChatByName(query) || cache.resolveContact(query);
        if (!resolved) {
          return { content: [{ type: "text", text: `No contact found matching "${query}". Sync contacts first.` }] };
        }
        const result = await callRenderer("sendMessage", [resolved.id, message]);
        return { content: [{ type: "text", text: `Message sent to ${resolved.name}: "${message}"` }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error sending message: ${err.message}` }], isError: true };
      }
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
