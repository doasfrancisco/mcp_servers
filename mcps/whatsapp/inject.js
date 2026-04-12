/**
 * inject.js — Injected into WhatsApp Web's page context via executeJavaScript().
 *
 * Runs in the MAIN WORLD — has full access to WhatsApp's webpack modules.
 * WhatsApp Web natively exposes window.require (webpack's __webpack_require__).
 * We just wait for it to be available, then use it to access Store modules.
 *
 * This is the same approach whatsapp-web.js uses — it calls window.require()
 * directly without any webpack chunk probing.
 */

(function () {
  "use strict";

  if (window.__waAPI) return; // already injected

  // ── Resolve webpack modules via window.require ──────────────

  function resolveModules() {
    if (typeof window.require !== "function") return null;

    const modules = {};

    // Step 1: Get all collections from WAWebCollections (Chat, Contact, Msg stores)
    // This is how whatsapp-web.js does it — WAWebCollections has the instantiated stores
    try {
      const collections = window.require("WAWebCollections");
      if (collections) {
        Object.assign(modules, collections);
        console.log("[wa-bridge] WAWebCollections keys:", Object.keys(collections).join(", "));
      }
    } catch (e) {
      console.warn("[wa-bridge] WAWebCollections not found:", e.message);
    }

    // Step 2: Additional modules not in collections
    const extras = {
      SendMessage: "WAWebSendMsgChatAction",
      MsgKey: "WAWebMsgKey",
      UserPrefs: "WAWebUserPrefsMeUser",
      SendSeen: "WAWebUpdateUnreadChatAction",
      SocketModel: "WAWebSocketModel",
      FindChat: "WAWebFindChatAction",
      WidFactory: "WAWebWidFactory",
      DBMessageFind: "WAWebDBMessageFindLocal",
    };

    for (const [key, moduleName] of Object.entries(extras)) {
      try {
        const mod = window.require(moduleName);
        if (mod) modules[key] = mod;
      } catch {}
    }

    // Step 3: Find ConversationMsgs (has loadEarlierMsgs for fetching message history)
    // Legacy whatsapp-web.js found it via: mR.findModule('loadEarlierMsgs')[0]
    // Modern: try known module names, then scan
    const convMsgCandidates = [
      "WAWebChatLoadMessages",
      "WAWebConversationMsgs",
      "WAWebMsgLoadUtils",
    ];
    for (const name of convMsgCandidates) {
      try {
        const mod = window.require(name);
        if (mod?.loadEarlierMsgs) {
          modules.ConversationMsgs = mod;
          break;
        }
      } catch {}
    }

    // Fallback: scan all loaded modules for one that exports loadEarlierMsgs
    if (!modules.ConversationMsgs && window.require.m) {
      for (const id of Object.keys(window.require.m)) {
        try {
          const mod = window.require(id);
          if (mod?.loadEarlierMsgs) {
            modules.ConversationMsgs = mod;
            console.log("[wa-bridge] Found ConversationMsgs via scan:", id);
            break;
          }
        } catch {}
      }
    }

    const found = Object.keys(modules).length;
    console.log(`[wa-bridge] Total modules resolved: ${found}`);
    console.log("[wa-bridge] Has ConversationMsgs:", !!modules.ConversationMsgs);
    if (found === 0) return null;

    return modules;
  }

  // ── API implementation ──────────────────────────────────────

  function createAPI(modules) {
    const api = { _ready: true, _modules: modules };

    async function resolveChat(chatId) {
      const store = modules.Chat;
      if (!store) throw new Error("Chat store not available");

      const wid = modules.WidFactory?.createWid ? modules.WidFactory.createWid(chatId) : chatId;

      // Prefer findOrCreateLatestChat — it fully hydrates the chat so
      // chat.msgs has all recent messages. Chat.get() returns a shell
      // with only the sidebar preview message.
      try {
        const result = await modules.FindChat?.findOrCreateLatestChat?.(wid);
        if (result?.chat) return result.chat;
      } catch {}

      return store.get(wid) || store.get(chatId) || null;
    }

    api.getContacts = () => {
      const store = modules.Contact;
      if (!store) throw new Error("Contact store not available");

      const models = store.getModelsArray ? store.getModelsArray() : [];
      console.log(`[wa-bridge] Contact store has ${models.length} models`);

      return models
        .filter((c) => {
          try {
            if (!c.id) return false;
            const id = c.id._serialized || c.id.toString();
            // Skip @lid (internal linked IDs, duplicate @c.us entries with wrong numbers)
            if (id.endsWith("@lid")) return false;
            // Skip groups and broadcasts
            if (id.endsWith("@g.us") || id.endsWith("@broadcast")) return false;
            // Include saved contacts (have a name in address book)
            return c.isMyContact || c.isAddressBookContact || !!c.name;
          } catch { return false; }
        })
        .map((c) => {
          try {
            const id = c.id._serialized || c.id.toString();
            return {
              id,
              name: c.name || null,
              pushname: c.pushname || c.notifyName || c.verifiedName || null,
              number: c.id?.user || null,
              isMyContact: !!(c.isMyContact || c.isAddressBookContact || c.name),
              isGroup: false,
              isUser: true,
            };
          } catch { return null; }
        })
        .filter(Boolean);
    };

    api.getChats = () => {
      const store = modules.Chat;
      if (!store) throw new Error("Chat store not available");

      const models = store.getModelsArray ? store.getModelsArray() : [];

      return models
        .map((c) => {
          try {
            const id = c.id._serialized || c.id.toString();
            // Derive isGroup from id suffix — reliable
            const isGroup = id.endsWith("@g.us");

            const chat = {
              id,
              name: c.name || c.formattedTitle || null,
              isGroup,
              timestamp: c.t ? new Date(c.t * 1000).toISOString() : null,
              unreadCount: c.unreadCount || 0,
              archived: c.archive || false,
              pinned: c.pin ? true : false,
            };

            // Last message — raw Store models don't have lastMsg property,
            // get it from the msgs collection instead
            try {
              const msgsArr = c.msgs?.getModelsArray?.();
              const lastMsg = msgsArr?.length ? msgsArr[msgsArr.length - 1] : null;
              if (lastMsg) {
                chat.lastMessage = {
                  body: lastMsg.body || null,
                  type: lastMsg.type || null,
                  timestamp: lastMsg.t ? new Date(lastMsg.t * 1000).toISOString() : null,
                  fromMe: lastMsg.id?.fromMe || false,
                };
              }
            } catch (e) {
              console.warn("[wa-bridge] lastMsg error for", id, e.message);
            }

            // Participants (groups only)
            try {
              if (isGroup && c.groupMetadata?.participants) {
                const pModels = c.groupMetadata.participants.getModelsArray
                  ? c.groupMetadata.participants.getModelsArray()
                  : Array.from(c.groupMetadata.participants);
                chat.participants = pModels
                  .filter(p => p.id)
                  .map((p) => ({
                    id: p.id._serialized,
                    isAdmin: p.isAdmin || false,
                    isSuperAdmin: p.isSuperAdmin || false,
                  }));
              }
            } catch (e) {
              console.warn("[wa-bridge] participants error for", id, e.message);
            }

            return chat;
          } catch { return null; }
        })
        .filter(Boolean);
    };

    // Convert raw DB results to Msg store models
    function toMsgModels(rawMessages) {
      const MsgStore = modules.Msg;
      if (!MsgStore) return rawMessages;
      const out = [];
      for (const m of rawMessages) {
        if (m && typeof m.serialize === "function") { out.push(m); continue; }
        const serialized = m?.id?._serialized || (typeof m === "string" ? m : null);
        let model = (serialized && MsgStore.get(serialized))
          || (m?.id && MsgStore.get(m.id._serialized || m.id))
          || null;
        if (!model && m && MsgStore.modelClass) {
          try { model = new MsgStore.modelClass(m); } catch {}
        }
        if (model) out.push(model);
      }
      return out;
    }

    // Serialize a message model for IPC
    function serializeMsg(m) {
      try {
        const authorId = m.author?._serialized || m.author;
        const fromId = m.from?._serialized || m.from;
        const senderId = authorId || fromId;
        const senderName = m.senderObj?.pushname || m.senderObj?.name || senderId;
        const msgType = m.type || "chat";
        let body = m.body || "";
        if (msgType !== "chat" && body.startsWith("/9j/")) body = "";
        return {
          id: m.id._serialized || m.id.toString(),
          sender: senderName,
          from: senderId,
          body,
          timestamp: m.t ? new Date(m.t * 1000).toISOString() : null,
          type: msgType,
          hasMedia: m.isMedia || false,
          isForwarded: m.isForwarded || false,
          hasQuotedMsg: !!m.quotedMsg,
        };
      } catch { return null; }
    }

    function serializeMessages(models, limit = null) {
      const selected = limit == null ? models : models.slice(-limit);
      return selected.map(serializeMsg).filter(Boolean);
    }

    // Query local IndexedDB for messages before an anchor.
    // Replaces the broken loadEarlierMsgs (WhatsApp Web removed
    // waitForChatLoading from the msgs collection in April 2026).
    // See: https://github.com/wwebjs/whatsapp-web.js/pull/201705
    async function findMessagesBefore(anchorId, count) {
      if (!modules.DBMessageFind || !modules.MsgKey) return [];

      const anchorKey = (anchorId instanceof modules.MsgKey)
        ? anchorId
        : modules.MsgKey.fromString?.(anchorId._serialized || anchorId.toString?.() || anchorId);
      if (!anchorKey) return [];

      const fn = modules.DBMessageFind.msgFindByDirection
        ? (a, n) => modules.DBMessageFind.msgFindByDirection({ anchor: a, count: n, direction: "before" })
        : (a, n) => modules.DBMessageFind.msgFindBefore({ anchor: a, count: n });

      const result = await fn(anchorKey, count);
      const raw = Array.isArray(result) ? result : result?.messages || [];
      if (result?.status === 404 || !raw.length) return [];
      return toMsgModels(raw);
    }

    function dedupeAndSort(models) {
      const seen = new Set();
      return models
        .filter(m => { const k = m.id?._serialized; if (!k || seen.has(k)) return false; seen.add(k); return true; })
        .sort((a, b) => (a.t || 0) - (b.t || 0));
    }

    api.getMessages = async (chatId, count = 50) => {
      let chat = await resolveChat(chatId);
      if (!chat) throw new Error(`Chat ${chatId} not found`);

      let models = chat.msgs?.getModelsArray ? chat.msgs.getModelsArray() : [];

      if (models.length < count) {
        const anchor = models[0]?.id || chat.lastReceivedKey;
        if (anchor) {
          const older = await findMessagesBefore(anchor, count - models.length);
          if (older.length) {
            const anchorMsg = modules.Msg?.get?.(anchor._serialized || anchor);
            models = dedupeAndSort([...older, ...(anchorMsg ? [anchorMsg] : []), ...models]);
          }
        }
      }

      return serializeMessages(models, count);
    };

    api.getMessagesUntil = async (chatId, stopAtTimestamp = null) => {
      let chat = await resolveChat(chatId);
      if (!chat) throw new Error(`Chat ${chatId} not found`);

      let models = chat.msgs?.getModelsArray ? chat.msgs.getModelsArray() : [];

      const coversTarget = () => {
        if (!stopAtTimestamp || !models.length) return false;
        const oldestTs = models[0]?.t ? new Date(models[0].t * 1000).toISOString() : null;
        return oldestTs && oldestTs <= stopAtTimestamp;
      };

      let batch = 100;
      while (!coversTarget()) {
        const anchor = models[0]?.id || chat.lastReceivedKey;
        if (!anchor) break;
        const older = await findMessagesBefore(anchor, batch);
        if (!older.length) break;
        models = dedupeAndSort([...older, ...models]);
        batch *= 2;
      }

      return serializeMessages(models);
    };

    api.sendMessage = async (chatId, text) => {
      const chat = modules.Chat?.get(chatId);
      if (!chat) throw new Error(`Chat ${chatId} not found`);

      if (modules.SendMessage?.sendMsgToChat) {
        await modules.SendMessage.sendMsgToChat(chat, text);
      } else if (modules.SendTextMsg?.sendTextMsgToChat) {
        await modules.SendTextMsg.sendTextMsgToChat(chat, text);
      } else {
        await chat.sendMessage(text);
      }

      return { success: true, chatId, text };
    };

    api.getConnectionState = () => {
      try {
        const socket = modules.SocketModel?.Socket;
        return socket?.state || "unknown";
      } catch {
        return "unknown";
      }
    };

    return api;
  }

  // ── Bootstrap ───────────────────────────────────────────────

  function tryInit() {
    // WhatsApp Web exposes window.require after its webpack runtime loads.
    // whatsapp-web.js waits for window.Debug?.VERSION as a readiness signal.
    if (typeof window.require !== "function") {
      console.log("[wa-bridge] window.require not available yet");
      return false;
    }

    // Also check that the app is fully loaded
    if (!window.Debug?.VERSION) {
      console.log("[wa-bridge] window.Debug.VERSION not set yet, app still loading");
      return false;
    }

    console.log("[wa-bridge] WhatsApp Web version:", window.Debug.VERSION);
    console.log("[wa-bridge] window.require is available, resolving modules...");

    const modules = resolveModules();
    if (!modules) {
      console.log("[wa-bridge] No modules resolved yet");
      return false;
    }

    if (!modules.Chat && !modules.Contact) {
      console.log("[wa-bridge] Chat and Contact modules not found");
      return false;
    }

    window.__waAPI = createAPI(modules);

    // Signal to preload/main that we're ready
    if (window.__electronBridge?.storeReady) {
      window.__electronBridge.storeReady();
    }

    console.log("[wa-bridge] API ready, modules:", Object.keys(modules).join(", "));
    return true;
  }

  // Listen for requests from main process (via preload)
  window.addEventListener("__wa_request", async (event) => {
    const { requestId, method, args } = event.detail;
    try {
      if (!window.__waAPI || !window.__waAPI[method]) {
        throw new Error(`Method ${method} not available`);
      }
      const result = await window.__waAPI[method](...(args || []));
      window.postMessage({ type: "__wa_response", requestId, result }, "*");
    } catch (err) {
      window.postMessage({ type: "__wa_response", requestId, error: err.message }, "*");
    }
  });

  // Try immediately, then retry every 2s for up to 60s
  if (!tryInit()) {
    let attempts = 0;
    const interval = setInterval(() => {
      attempts++;
      if (tryInit() || attempts >= 30) {
        clearInterval(interval);
        if (!window.__waAPI) {
          console.error("[wa-bridge] Failed to initialize after 60s");
        }
      }
    }, 2000);
  }
})();
