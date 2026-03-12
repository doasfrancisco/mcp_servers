import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest } from "@modelcontextprotocol/sdk/types.js";
import { randomUUID } from "node:crypto";
import express from "express";
import cors from "cors";
import { z } from "zod";
import * as wa from "./whatsapp_client.js";

const PORT = parseInt(process.argv.find((_, i, a) => a[i - 1] === "--port") || "39571", 10);

// ── Tool registration ─────────────────────────────────────────
// Each MCP session needs its own McpServer instance (the SDK binds
// one transport per server). Tools are stateless — they all share
// the same wa.* functions and cache files.

function createServer() {
  const server = new McpServer({
    name: "whatsapp",
    version: "1.0.0",
    instructions: `When asked to show messages:
1. If you don't have an exact contact name, use whatsapp_find to resolve it first.
2. Try whatsapp_get_messages — it reads from local cache with zero API calls.
3. Only if the cache is empty, ask the user before syncing.

CRITICAL — whatsapp_get_messages returns pre-formatted conversation output.
You MUST paste the ENTIRE text content into your response as a verbatim code block.
Do NOT summarize, paraphrase, abbreviate, or skip any messages. Show EVERY line.`,
  });

  // ── Sync (the ONLY tool that calls the WhatsApp API) ──────────

  server.tool(
    "whatsapp_sync",
    `Sync WhatsApp data from the API into the local cache.
NEVER call this to read messages — use whatsapp_get_messages first.
Only sync messages if whatsapp_get_messages returned empty and the user agreed to sync.
This is the ONLY tool that makes API calls — all other tools read from cache.
With no params: syncs contacts and chats in parallel.
With what="messages" + chats array: fetches and caches messages for specific chats.
Returns stats on what was synced.`,
    {
      what: z.enum(["messages"]).optional().describe('Optional: "messages" to sync messages for specific chats. Omit to sync contacts+chats.'),
      chats: z.array(z.string()).optional().describe("Chat names to sync messages for (required when what=\"messages\")"),
      since: z.string().optional().describe("ISO date (YYYY-MM-DD) — sync messages from this date. Default: 2 days ago."),
    },
    async ({ what, chats, since }) => {
      try {
        if (what === "messages") {
          if (!chats || chats.length === 0) {
            return { content: [{ type: "text", text: "Provide a chats array with chat names to sync messages for." }] };
          }
          const results = await wa.syncMessages(chats, since);
          return { content: [{ type: "text", text: JSON.stringify(results, null, 2) }] };
        }

        // Default: sync contacts + chats
        const result = await wa.syncAll();
        let text = `Contacts: ${result.contacts.error ? "FAILED" : `${result.contacts.synced} total, ${result.contacts.added} new, ${result.contacts.changed} changed`}.\nChats: ${result.chats.error ? "FAILED" : `${result.chats.synced} total, ${result.chats.added} new, ${result.chats.changed} changed, ${result.chats.updated} updated`}.`;
        if (result.chats.updatedChats.length > 0) {
          text += `\n\nUpdated chats:\n${JSON.stringify(result.chats.updatedChats, null, 2)}`;
        }
        if (result.contacts.skipped?.length > 0) text += `\n\nContacts skipped (${result.contacts.skipped.length}):\n${JSON.stringify(result.contacts.skipped, null, 2)}`;
        if (result.chats.skipped?.length > 0) text += `\n\nChats skipped (${result.chats.skipped.length}):\n${JSON.stringify(result.chats.skipped, null, 2)}`;
        if (result.contacts.error) text += `\n\nContacts error:\n${result.contacts.error}`;
        if (result.chats.error) text += `\n\nChats error:\n${result.chats.error}`;
        return { content: [{ type: "text", text }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── Read tools (cache-only — never call the API) ──────────────

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
      query: z.string().optional().describe("Name or phone number to search for (substring match on name, pushname, and number)"),
      tag: z.string().optional().describe("Filter by tag (e.g. family, work, partner, followup)"),
      from: z.string().optional().describe("ISO date (YYYY-MM-DD) — return entries with activity on or after this date"),
      filter: z.enum(["pinned", "unread", "groups"]).optional().describe("Filter: pinned, unread, or groups only"),
    },
    async ({ query, tag, from, filter }) => {
      // Relationship words → tag fallback
      const RELATIONSHIP_TAGS = {
        girlfriend: "partner", boyfriend: "partner", wife: "partner", husband: "partner",
        partner: "partner", spouse: "partner", fiance: "partner", fiancee: "partner",
        coworker: "work", colleague: "work", boss: "work",
        brother: "family", sister: "family", mom: "family", dad: "family",
        mother: "family", father: "family", cousin: "family", uncle: "family", aunt: "family",
      };

      try {
        let results = wa.find({ query, tag, from, filter });

        // Fallback: if query matched no contacts, check if it maps to a tag
        if (results.length === 0 && query && !tag) {
          const mapped = RELATIONSHIP_TAGS[query.toLowerCase()];
          if (mapped) {
            results = wa.find({ tag: mapped, from, filter });
            if (results.length > 0) {
              return { content: [{ type: "text", text: `No contact named "${query}", but found results via the "${mapped}" tag:\n${JSON.stringify(results, null, 2)}` }] };
            }
          }
        }

        if (results.length === 0) {
          const reason = tag
            ? `No results found with tag "${tag}".`
            : query
              ? `No results found matching "${query}".`
              : "No results found. The cache may be empty — use whatsapp_sync first.";
          return { content: [{ type: "text", text: reason }] };
        }
        return { content: [{ type: "text", text: JSON.stringify(results, null, 2) }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  server.tool(
    "whatsapp_tag_contacts",
    `Add or remove tags from one or more WhatsApp contacts in a single call.
Each entry specifies a contact, the tags, and whether to add or remove.
Looks up each contact by name or phone number in the local cache — sync contacts first if needed.
Default tags: family, work, partner, followup. Custom tags are auto-created when first used.
If a contact is not found but candidates exist, all possible matches are listed —
present every candidate to the user and ask which one they meant before retrying.`,
    {
      entries: z
        .array(
          z.object({
            contact: z.string().describe("Contact or group name, or phone number"),
            tags: z.array(z.string()).describe('Tag names (e.g. ["family", "followup"])'),
            action: z.enum(["add", "remove"]).default("add").describe('"add" (default) or "remove"'),
          })
        )
        .describe("List of { contact, tags, action } entries to process"),
    },
    async ({ entries }) => {
      const lines = [];
      for (const { contact, tags, action = "add" } of entries) {
        try {
          const result =
            action === "remove"
              ? wa.untagContact(contact, tags)
              : wa.tagContact(contact, tags);
          if (result.error) {
            lines.push(`"${contact}": ${result.error}`);
          } else if (result.candidates) {
            lines.push(`"${contact}": not found. Did you mean: ${result.candidates.join(", ")}?`);
          } else {
            lines.push(`"${result.contact}": [${result.tags.join(", ")}]`);
          }
        } catch (err) {
          lines.push(`"${contact}": Error — ${err.message}`);
        }
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    }
  );

  // ── Message formatter ────────────────────────────────────────

  const MEDIA_LABELS = {
    image: "[image]",
    video: "[video]",
    audio: "[audio]",
    ptt: "[voice note]",
    document: "[document]",
    sticker: "[sticker]",
    call_log: "[call]",
    vcard: "[contact]",
  };

  const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function formatMessages(messages, chatName, mentionMap = {}) {
    const lines = [];
    let lastDate = "";

    for (const m of messages) {
      const dt = new Date(m.timestamp);
      const dateKey = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;

      // Date header when day changes
      if (dateKey !== lastDate) {
        lastDate = dateKey;
        const dayName = DAY_NAMES[dt.getDay()];
        const month = MONTH_NAMES[dt.getMonth()];
        const day = dt.getDate();
        if (lines.length > 0) lines.push(""); // blank line before new day
        lines.push(`-- ${dayName}, ${month} ${day} --`);
      }

      // Skip pinned_message system events
      if (m.type === "pinned_message") continue;

      // Time
      const hours = dt.getHours();
      const mins = dt.getMinutes().toString().padStart(2, "0");
      const ampm = hours >= 12 ? "PM" : "AM";
      const h12 = hours % 12 || 12;
      const time = `${h12}:${mins} ${ampm}`;

      // Sender direction
      const fromMe = m.id.startsWith("true_");
      const sender = fromMe ? "< You" : `> ${m.sender || chatName}`;

      // Body
      let body = m.body || "";
      const label = MEDIA_LABELS[m.type];
      if (label && m.type !== "chat") {
        if (m.type === "document" && body) {
          body = `[${body}]`;
        } else {
          body = body ? `${label} ${body}` : label;
        }
      }

      // Resolve @mentions (e.g. @13061113008215 -> @Mama Salas)
      body = body.replace(/@(\d{5,})/g, (match, num) => {
        const name = mentionMap[num];
        return name ? `@${name}` : match;
      });

      lines.push(`${sender} (${time}) -- ${body}`);
    }

    return lines.join("\n");
  }

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
        const result = wa.getMessages(query, since);
        if (result.error) {
          return { content: [{ type: "text", text: result.error }] };
        }
        if (result.messages.length === 0) {
          return { content: [{ type: "text", text: `No messages found for "${result.chat}". Want me to sync?` }] };
        }
        const mentionMap = wa.getMentionMap();
        const formatted = formatMessages(result.messages, result.chat, mentionMap);
        const output = `[VERBATIM — paste this entire block into your response. Do NOT summarize or skip lines.]\n\n${formatted}`;
        return { content: [{ type: "text", text: output, annotations: { audience: ["user"], priority: 1.0 } }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  return server;
}

// ── Start ─────────────────────────────────────────────────────

async function main() {
  wa.init();

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
      // Stale session ID (e.g. server restarted) — auto-create a new session
      // so the client doesn't need to re-initialize manually.
      if (sessionId) {
        console.error(`[whatsapp-mcp] Stale session ${sessionId}, auto-creating new session`);
        const transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => sessionId,
        });
        transport.onclose = () => { delete transports[sessionId]; };
        const server = createServer();
        await server.connect(transport);
        // Bypass the SDK's initialization handshake — the server and tools
        // are fully configured after connect(), only the transport's internal
        // _initialized flag needs to be set.
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

  app.listen(PORT, () => {
    console.error(`[whatsapp-mcp] Server running on http://localhost:${PORT}/mcp`);
  });
}

main().catch((err) => {
  console.error("[whatsapp-mcp] Fatal:", err);
  process.exit(1);
});

// Shutdown — force-kill Chrome directly, no CDP round-trip that can hang
function shutdown() {
  console.error("[whatsapp-mcp] Shutting down...");
  wa.killOrphanedChrome();
  process.exit(0);
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
