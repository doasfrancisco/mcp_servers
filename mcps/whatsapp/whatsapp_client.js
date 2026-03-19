import pkg from "whatsapp-web.js";
const { Client, LocalAuth } = pkg;
import { existsSync, mkdirSync, readFileSync, writeFileSync, unlinkSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";
import { platform } from "os";

const __dirname = dirname(fileURLToPath(import.meta.url));
const AUTH_DIR = join(__dirname, ".wwebjs_auth");
const CACHE_DIR = join(__dirname, ".wwebjs_cache");
const AUTH_MARKER = join(AUTH_DIR, ".authenticated");
const CONTACTS_CACHE = join(__dirname, "contacts.json");
const CHATS_CACHE = join(__dirname, "chats.json");
const TAGS_CACHE = join(__dirname, "tags.json");
const MESSAGES_DIR = join(__dirname, "messages");

const DEFAULT_TAGS = {
  family: { description: "Family members" },
  work: { description: "Work and professional contacts" },
  partner: { description: "Partner" },
  followup: { description: "Follow-ups and things to track" },
};

let client = null;
let readyTimer = null;
const MAX_RECONNECT_ATTEMPTS = 3;
const READY_TIMEOUT_MS = 15_000;
const DESTROY_TIMEOUT_MS = 10_000;
const RECONNECT_DEBOUNCE_MS = 5_000;
const STABILITY_MS = 15_000;
const WAIT_FOR_READY_MS = 15_000;
const DEAD_RECOVERY_MS = 60_000;

// Explicit state machine — replaces the old boolean flags (ready, reconnecting)
// that had race conditions when multiple disconnect triggers fired simultaneously.
const State = { INITIALIZING: "INITIALIZING", READY: "READY", RECONNECTING: "RECONNECTING", DEAD: "DEAD" };
let state = State.INITIALIZING;
let reconnectAttempts = 0;
let lastReconnectTime = 0;
let stabilityTimer = null;

// ── Orphan cleanup ────────────────────────────────────────────
// On Windows, SIGTERM kills the process unconditionally — the graceful
// shutdown handler never fires, leaving Puppeteer's Chrome alive.
// On startup, find any Chrome with our .wwebjs_auth user-data-dir and kill it.

export function killOrphanedChrome() {
  try {
    if (platform() === "win32") {
      // Only match the root browser process (no --type= flag). taskkill /T kills its children.
      const result = execSync(
        'wmic process where "Name=\'chrome.exe\' AND CommandLine like \'%.wwebjs_auth%\' AND NOT CommandLine like \'%--type=%\'" get ProcessId /format:list',
        { encoding: "utf-8", timeout: 5000, stdio: ["pipe", "pipe", "pipe"] }
      ).trim();
      const pids = result.match(/ProcessId=(\d+)/g)?.map((m) => m.split("=")[1]) || [];
      for (const pid of pids) {
        try {
          execSync(`taskkill /PID ${pid} /T /F`, { timeout: 5000, stdio: "pipe" });
          console.error(`[whatsapp] Killed orphaned Chrome tree (PID ${pid})`);
        } catch {}
      }
    } else {
      execSync(`pkill -f '.wwebjs_auth'`, { timeout: 5000, stdio: "pipe" });
      console.error("[whatsapp] Killed orphaned Chrome processes");
    }
  } catch {
    // No matching processes or command failed — both fine
  }
}

// ── Init & auth ───────────────────────────────────────────────

/**
 * Initialize and return the WhatsApp client.
 * First run opens a browser for QR auth; subsequent runs reconnect headlessly.
 * Uses a marker file (.authenticated) written after successful auth — directory
 * existence alone is not reliable because LocalAuth creates it before auth completes.
 */
export function init() {
  if (client) return client;

  const hasSession = existsSync(AUTH_MARKER);
  console.error(`[whatsapp] Session marker exists: ${hasSession}, headless: ${hasSession}`);

  client = new Client({
    authStrategy: new LocalAuth({ dataPath: AUTH_DIR }),
    puppeteer: {
      headless: hasSession,
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
    webVersionCache: {
      type: "local",
      path: CACHE_DIR,
    },
  });

  client.on("qr", (qr) => {
    if (hasSession) {
      // Session expired — we launched headless because the marker existed,
      // but WhatsApp wants a new QR scan. Delete marker and reconnect with
      // a visible browser so the user can scan.
      console.error("[whatsapp] QR received in headless mode — session expired, reconnecting with browser...");
      try { unlinkSync(AUTH_MARKER); } catch {}
      reconnectAttempts = 0;
      reconnect("qr_expired");
      return;
    }
    console.error("[whatsapp] QR code received — scan with your phone");
    console.error("[whatsapp] If no browser opened, copy this QR string into a QR viewer:");
    console.error(qr);
  });

  client.on("authenticated", () => {
    console.error("[whatsapp] Authenticated");
    try {
      writeFileSync(AUTH_MARKER, new Date().toISOString());
    } catch {}
    // If ready doesn't fire within 30s after auth, stores are hung — retry
    clearTimeout(readyTimer);
    readyTimer = setTimeout(() => {
      if (state !== State.READY) {
        console.error("[whatsapp] Ready timeout — authenticated but stores never loaded, retrying");
        reconnect("ready_timeout");
      }
    }, READY_TIMEOUT_MS);
  });

  client.on("auth_failure", (msg) => {
    console.error("[whatsapp] Auth failure:", msg);
    try {
      unlinkSync(AUTH_MARKER);
    } catch {}
    // Session expired — reconnect so next init() sees no marker and opens browser for QR
    reconnectAttempts = 0;
    reconnect("auth_failure");
  });

  client.on("ready", () => {
    console.error("[whatsapp] Client ready");
    clearTimeout(readyTimer);
    state = State.READY;
    // Only reset counter after sustained stability — prevents
    // flaky connections from resetting the counter on every brief READY.
    clearTimeout(stabilityTimer);
    stabilityTimer = setTimeout(() => {
      if (state === State.READY) {
        reconnectAttempts = 0;
        lastReconnectTime = 0;
        console.error("[whatsapp] Connection stable — counter reset");
      }
    }, STABILITY_MS);
  });

  // Log state transitions for debugging — helps diagnose what happens before a disconnect.
  client.on("change_state", (waState) => {
    console.error(`[whatsapp] State changed: ${waState}`);
  });

  client.on("disconnected", (reason) => {
    console.error("[whatsapp] Disconnected:", reason);
    // The library already calls this.destroy() after emitting 'disconnected',
    // so we pass the source to avoid double-destroying.
    reconnect("disconnected_event");
  });

  client.initialize().catch((err) => {
    console.error("[whatsapp] Initialize error:", err.message);
    // Only retry if we had a valid session — if QR was needed, don't loop
    if (state !== State.READY && existsSync(AUTH_MARKER)) {
      console.error("[whatsapp] Initialize failed with valid session — retrying");
      reconnect("initialize_error");
    }
  });

  return client;
}

/**
 * Destroy the current client and reinitialize.
 * Capped at MAX_RECONNECT_ATTEMPTS consecutive failures to avoid infinite loops.
 * Counter resets after STABILITY_MS of sustained READY (not immediately on ready).
 * DEAD state is auto-recovered by withReconnect after DEAD_RECOVERY_MS cooldown.
 *
 * @param {string} source — identifies the caller to handle double-destroy correctly:
 *   - "disconnected_event": library already called destroy(), skip our destroy
 *   - anything else: we initiate the destroy ourselves
 *
 * Debounce: a single disconnect fires multiple handlers (withReconnect catches the
 * error, library emits 'disconnected', ready timeout fires). Timestamp debounce
 * ensures only one reconnect cycle runs per disconnect event. If stuck in
 * RECONNECTING past the debounce window, allows a new attempt.
 */
async function reconnect(source = "unknown") {
  // Permanently dead — skip (auto-recovery happens in withReconnect)
  if (state === State.DEAD) {
    console.error(`[whatsapp] Reconnect skipped (state=DEAD, source=${source})`);
    return;
  }

  // Debounce: skip duplicate triggers. If still RECONNECTING but debounce
  // has passed, the previous attempt is stuck — allow a new one.
  const now = Date.now();
  if (now - lastReconnectTime < RECONNECT_DEBOUNCE_MS) {
    console.error(`[whatsapp] Reconnect debounced (${now - lastReconnectTime}ms since last, source=${source})`);
    return;
  }

  reconnectAttempts++;
  if (reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
    console.error(`[whatsapp] Max reconnect attempts (${MAX_RECONNECT_ATTEMPTS}) reached — giving up. Will auto-recover after ${DEAD_RECOVERY_MS / 1000}s.`);
    state = State.DEAD;
    return;
  }

  state = State.RECONNECTING;
  lastReconnectTime = now;
  clearTimeout(readyTimer);
  clearTimeout(stabilityTimer);
  console.error(`[whatsapp] Reconnecting (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}, source=${source})...`);

  if (client) {
    if (source === "disconnected_event") {
      // The library already called this.destroy() (without await) after emitting
      // 'disconnected'. Give it a moment to close Chrome, then force-kill stragglers.
      await new Promise((r) => setTimeout(r, 2000));
      killOrphanedChrome();
    } else {
      try {
        await Promise.race([
          client.destroy(),
          new Promise((_, reject) => setTimeout(() => reject(new Error("destroy timeout")), DESTROY_TIMEOUT_MS)),
        ]);
      } catch (err) {
        // Graceful destroy failed or timed out — force-kill Chrome
        console.error(`[whatsapp] Graceful destroy failed: ${err.message} — force-killing Chrome`);
        killOrphanedChrome();
      }
    }
    client = null;
  }

  // State stays RECONNECTING — init() sets up the client and handlers,
  // the 'ready' event will transition state to READY.
  init();
}

export function isReady() {
  return state === State.READY;
}

export async function destroy() {
  clearTimeout(readyTimer);
  clearTimeout(stabilityTimer);
  if (client) {
    await client.destroy();
    client = null;
    state = State.DEAD;
  }
}

function assertReady() {
  switch (state) {
    case State.READY:
      return;
    case State.RECONNECTING:
      throw new Error(
        `WhatsApp is reconnecting (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}) — try again in ~15 seconds.`
      );
    case State.DEAD:
      throw new Error(
        "WhatsApp reconnection failed after all retries. Restart the MCP server to recover."
      );
    case State.INITIALIZING:
      throw new Error(
        "WhatsApp client is initializing — try again in ~15 seconds."
      );
    default:
      throw new Error(
        "WhatsApp client is not running. Restart the MCP server."
      );
  }
}

/**
 * Wait until state becomes READY, or throw if DEAD / timed out.
 * Used by withReconnect to wait after triggering a reconnect.
 */
const API_TIMEOUT_MS = 15_000;

async function waitForReady(timeoutMs = WAIT_FOR_READY_MS) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (state === State.READY) return;
    if (state === State.DEAD) throw new Error("WhatsApp reconnection failed permanently.");
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error("Timed out waiting for WhatsApp to reconnect.");
}

function isSessionError(msg) {
  return (
    msg === "API call timeout" ||
    msg.includes("detached Frame") ||
    msg.includes("Session closed") ||
    msg.includes("Execution context was destroyed")
  );
}

/**
 * Wrap an async function that calls the WhatsApp API.
 * - Auto-recovers from DEAD state after cooldown.
 * - Waits for READY if currently reconnecting/initializing.
 * - On session errors: triggers reconnect, waits, retries once.
 * - Stores still loading: tell caller to retry.
 */
async function withReconnect(fn) {
  // Auto-recover from DEAD state after cooldown
  if (state === State.DEAD && Date.now() - lastReconnectTime > DEAD_RECOVERY_MS) {
    console.error("[whatsapp] Attempting recovery from DEAD state...");
    state = State.INITIALIZING;
    reconnectAttempts = 0;
    client = null;
    init();
  }

  // Wait if not ready (covers INITIALIZING, RECONNECTING, and recovered DEAD)
  if (state !== State.READY) {
    await waitForReady();
  }

  try {
    return await Promise.race([
      fn(),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error("API call timeout")), API_TIMEOUT_MS)
      ),
    ]);
  } catch (err) {
    const msg = err.message || "";

    // Session errors — reconnect, wait, retry once
    if (isSessionError(msg)) {
      const source = msg === "API call timeout" ? "api_timeout" : "detached_frame";
      console.error(`[whatsapp] Session error (${source}): ${msg} — reconnecting and retrying`);
      reconnect(source);
      await waitForReady();

      // Retry once after successful reconnect
      return await Promise.race([
        fn(),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error("API call timeout")), API_TIMEOUT_MS)
        ),
      ]);
    }

    if (msg.includes("is not a function") || msg.includes("Cannot read properties")) {
      console.error(`[whatsapp] Stores still loading: ${msg}`);
      throw new Error("WhatsApp is still loading — try again in ~15 seconds.");
    }
    throw err;
  }
}

// ── Cache helpers ─────────────────────────────────────────────

function readCache(path) {
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf-8"));
}

function writeCache(path, data) {
  try {
    writeFileSync(path, JSON.stringify(data, null, 2));
  } catch {}
}

/**
 * Build a number → contact name map from the contacts cache.
 * Maps both the raw number and @lid/@c.us number portions so @mentions can be resolved.
 */
export function getMentionMap() {
  const contacts = readCache(CONTACTS_CACHE) || [];
  const map = {};
  for (const c of contacts) {
    const name = c.name || c.pushname || null;
    if (!name) continue;
    // Map the number portion of the id (e.g. "13061113008215" from "13061113008215@lid")
    const num = c.id.split("@")[0];
    if (num && !map[num]) map[num] = name;
    // Also map the explicit number field
    if (c.number && !map[c.number]) map[c.number] = name;
  }
  return map;
}

// ── Sync (API calls — the only functions that touch the network) ──

/** Fields tracked for changes — if any differ, snapshot old values. */
const CONTACT_TRACKED_FIELDS = ["name", "pushname", "number"];

/**
 * Sync contacts from the API. Merges with existing cache: new contacts are
 * added, changed contacts keep a `previous` array with snapshots of old values.
 * Returns { synced: number, added: number, changed: number }.
 */
export async function syncContacts() {
  // Bypass client.getContacts() — it crashes inside page.evaluate when any
  // contact in the Store has an undefined id (whatsapp-web.js calls serialize()
  // which hits a memoize getter that requires id). Instead, run our own evaluate
  // that filters out malformed entries before getContactModel touches them.
  const { contacts: rawContacts, skippedInBrowser } = await withReconnect(() =>
    client.pupPage.evaluate(() => {
      const models = window.Store.Contact.getModelsArray();
      const contacts = [];
      const skippedInBrowser = [];
      for (const c of models) {
        try {
          if (!c.id) {
            let info;
            try { info = { name: c.name, pushname: c.pushname, number: c.number }; } catch { info = "unreadable"; }
            skippedInBrowser.push({ error: "missing id", info });
            continue;
          }
          contacts.push(window.WWebJS.getContactModel(c));
        } catch (e) {
          let info;
          try { info = { id: c.id?._serialized, name: c.name, pushname: c.pushname, number: c.number }; } catch { info = "unreadable"; }
          skippedInBrowser.push({ error: e.message, info });
        }
      }
      return { contacts, skippedInBrowser };
    })
  );
  if (skippedInBrowser.length) {
    console.error(`[whatsapp] syncContacts: ${skippedInBrowser.length} contacts skipped in browser`, skippedInBrowser);
  }
  const contacts = rawContacts;

  // Filter to saved contacts only. The flatMap also catches any remaining
  // serialization issues that survived the browser-side filter.
  const skippedEntries = [...skippedInBrowser];
  const fresh = contacts.flatMap((c) => {
    try {
      if (!c.id || !c.isMyContact) return [];
      return [{
        id: c.id._serialized,
        name: c.name || null,
        pushname: c.pushname || null,
        number: c.userid || c.number,
        isMyContact: c.isMyContact,
        isGroup: c.isGroup,
        isUser: c.isUser,
      }];
    } catch (err) {
      // Capture whatever we can about the malformed entry
      let info;
      try { info = { name: c.name, pushname: c.pushname, number: c.number }; } catch { info = "unreadable"; }
      skippedEntries.push({ error: err.message, info });
      console.error(`[whatsapp] syncContacts: skipping malformed contact: ${err.message}`, info);
      return [];
    }
  });

  const cached = readCache(CONTACTS_CACHE);
  if (!cached) {
    writeCache(CONTACTS_CACHE, fresh);
    return { synced: fresh.length, added: fresh.length, changed: 0, skipped: skippedEntries };
  }

  const cacheIndex = Object.fromEntries(cached.map((c) => [c.id, c]));
  let added = 0;
  let changed = 0;

  const merged = fresh.map((fc) => {
    const old = cacheIndex[fc.id];
    if (!old) {
      added++;
      return fc;
    }

    const hasChanged = CONTACT_TRACKED_FIELDS.some((f) => fc[f] !== old[f]);
    if (!hasChanged) {
      if (old.previous) fc.previous = old.previous;
      return fc;
    }

    changed++;
    const snapshot = {};
    for (const f of CONTACT_TRACKED_FIELDS) snapshot[f] = old[f];
    snapshot.changedAt = new Date().toISOString();
    fc.previous = [...(old.previous || []), snapshot];
    return fc;
  });

  writeCache(CONTACTS_CACHE, merged);
  return { synced: merged.length, added, changed, skipped: skippedEntries };
}

/** Fields tracked for chat changes. */
const CHAT_TRACKED_FIELDS = ["name"];

/**
 * Sync all chats from the API. Saves chat metadata (not messages) to chats.json.
 * For groups, includes participant list. Merges with existing cache.
 * Returns { synced: number, added: number, changed: number }.
 */
export async function syncChats() {
  const chats = await withReconnect(() => client.getChats());

  // Filter inside flatMap — even .id access on proxy objects can throw.
  const skippedEntries = [];
  const fresh = chats.flatMap((c) => {
    try {
      if (!c.id) return [];
        const chat = {
          id: c.id._serialized,
          name: c.name || null,
          isGroup: c.isGroup,
          timestamp: c.timestamp ? new Date(c.timestamp * 1000).toISOString() : null,
          unreadCount: c.unreadCount || 0,
          archived: c.archived || false,
          pinned: c.pinned || false,
        };

        try {
          if (c.lastMessage) {
            chat.lastMessage = {
              body: c.lastMessage.body || null,
              type: c.lastMessage.type,
              timestamp: c.lastMessage.timestamp
                ? new Date(c.lastMessage.timestamp * 1000).toISOString()
                : null,
              fromMe: c.lastMessage.fromMe || false,
            };
          }
        } catch {
          // lastMessage getter can fail on malformed message data — skip it
        }

        try {
          if (c.isGroup && c.participants) {
            chat.participants = c.participants
              .filter((p) => p.id)
              .map((p) => ({
                id: p.id._serialized,
                isAdmin: p.isAdmin || false,
                isSuperAdmin: p.isSuperAdmin || false,
              }));
          }
        } catch {
          // participants getter can fail on malformed group data — skip it
        }

        return [chat];
      } catch (err) {
        let info;
        try { info = { name: c.name }; } catch { info = "unreadable"; }
        skippedEntries.push({ error: err.message, info });
        console.error(`[whatsapp] syncChats: skipping malformed chat: ${err.message}`, info);
        return [];
      }
    });

  const cached = readCache(CHATS_CACHE);
  if (!cached) {
    const result = { lastRefresh: new Date().toISOString(), data: fresh };
    writeCache(CHATS_CACHE, result);
    return { synced: fresh.length, added: fresh.length, changed: 0, updated: 0, updatedChats: [], skipped: skippedEntries };
  }

  const cacheIndex = Object.fromEntries(cached.data.map((c) => [c.id, c]));
  let added = 0;
  let changed = 0;
  const updatedChats = [];

  const merged = fresh.map((fc) => {
    const old = cacheIndex[fc.id];
    if (!old) {
      added++;
      return fc;
    }

    // Identity change (e.g. group renamed)
    const hasChanged = CHAT_TRACKED_FIELDS.some((f) => fc[f] !== old[f]);
    if (hasChanged) {
      changed++;
      const snapshot = {};
      for (const f of CHAT_TRACKED_FIELDS) snapshot[f] = old[f];
      snapshot.changedAt = new Date().toISOString();
      fc.previous = [...(old.previous || []), snapshot];
    } else {
      if (old.previous) fc.previous = old.previous;
    }

    // Activity change (new messages or unread count changed)
    if (fc.timestamp !== old.timestamp || fc.unreadCount !== old.unreadCount) {
      updatedChats.push({ name: fc.name, id: fc.id, archived: fc.archived, unreadCount: fc.unreadCount });
    }

    return fc;
  });

  const result = { lastRefresh: new Date().toISOString(), data: merged };
  writeCache(CHATS_CACHE, result);
  return { synced: merged.length, added, changed, updated: updatedChats.length, updatedChats, skipped: skippedEntries };
}

/**
 * Sync both contacts and chats in parallel.
 * Returns combined stats from both operations.
 */
export async function syncAll() {
  const [contactsResult, chatsResult] = await Promise.allSettled([syncContacts(), syncChats()]);

  const contacts = contactsResult.status === "fulfilled"
    ? contactsResult.value
    : { synced: 0, added: 0, changed: 0, skipped: [], error: contactsResult.reason?.stack || contactsResult.reason?.message };

  const chats = chatsResult.status === "fulfilled"
    ? chatsResult.value
    : { synced: 0, added: 0, changed: 0, updated: 0, updatedChats: [], skipped: [], error: chatsResult.reason?.stack || chatsResult.reason?.message };

  return {
    contacts: { synced: contacts.synced, added: contacts.added, changed: contacts.changed, skipped: contacts.skipped, error: contacts.error },
    chats: { synced: chats.synced, added: chats.added, changed: chats.changed, updated: chats.updated, updatedChats: chats.updatedChats || [], skipped: chats.skipped, error: chats.error },
  };
}

/**
 * Sync messages for specific chats from the API into local cache files.
 * Fetches messages back to `since` date (default: 2 days ago) by growing batch
 * sizes until the oldest fetched message is older than the cutoff.
 * Deduplicates by message id, sorts by timestamp. Re-syncing with a wider date
 * range merges cleanly — existing messages are kept, new older ones are added.
 */
export async function syncMessages(chatNames, since) {
  if (!existsSync(MESSAGES_DIR)) mkdirSync(MESSAGES_DIR);

  const cutoff = since
    ? new Date(since + "T00:00:00Z")
    : new Date(Date.now() - 2 * 24 * 60 * 60 * 1000);
  const cutoffISO = cutoff.toISOString();

  const results = [];
  for (const name of chatNames) {
    const chat = await findChat(name);
    if (!chat) {
      results.push({ chat: name, error: "not found" });
      continue;
    }

    // Fetch in growing batches until we've reached past the cutoff date
    let messages = [];
    let batch = 50;
    const MAX_BATCH = 1000;
    while (batch <= MAX_BATCH) {
      messages = await withReconnect(() => getChatMessages(chat, batch));
      if (messages.length === 0 || messages.length < batch) break;
      // messages[0] is the oldest (chronological order)
      if (messages[0].timestamp <= cutoffISO) break;
      batch *= 2;
    }

    // Keep only messages within the date range
    const filtered = messages.filter((m) => m.timestamp >= cutoffISO);

    const filePath = join(MESSAGES_DIR, `${chat.id._serialized}.json`);
    const existing = readCache(filePath) || [];

    // Merge: index existing by id, overwrite with fresh
    const index = Object.fromEntries(existing.map((m) => [m.id, m]));
    for (const m of filtered) index[m.id] = m;
    const merged = Object.values(index).sort((a, b) => a.timestamp.localeCompare(b.timestamp));

    writeCache(filePath, merged);
    results.push({ chat: chat.name, id: chat.id._serialized, synced: filtered.length, total: merged.length, added: merged.length - existing.length });
  }
  return results;
}

// ── Read (cache-only — never call the API) ────────────────────

/**
 * Unified search across contacts and chats caches.
 * Merges both sources into a single index — contacts provide identity,
 * chats provide activity metadata. Supports filtering by query, tag, date, and type.
 * Never calls the API.
 */
export function find({ query, tag, from, filter } = {}) {
  // Default to today's activity when browsing (no specific search params)
  if (!query && !tag && !from && !filter) {
    const now = new Date();
    from = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }

  const tagData = readTags();
  const contacts = readCache(CONTACTS_CACHE) || [];
  const chatCache = readCache(CHATS_CACHE);
  const chats = chatCache?.data || [];

  // Build a merged index by id — contacts provide identity, chats provide activity
  const index = {};

  for (const c of contacts) {
    index[c.id] = { ...c, tags: tagData.contacts[c.id] || [] };
  }

  for (const c of chats) {
    if (index[c.id]) {
      // Enrich existing contact with chat metadata
      Object.assign(index[c.id], {
        timestamp: c.timestamp,
        unreadCount: c.unreadCount,
        archived: c.archived,
        pinned: c.pinned,
        lastMessage: c.lastMessage,
        participants: c.participants,
      });
    } else {
      // Group or chat not in contacts — add it
      index[c.id] = { ...c, tags: tagData.contacts[c.id] || [] };
    }
  }

  let results = Object.values(index);

  // Filter by tag
  if (tag) {
    results = results.filter((r) => r.tags.includes(tag));
  }

  // Filter by name or phone number query
  if (query) {
    const q = query.toLowerCase();
    results = results.filter(
      (r) =>
        r.name?.toLowerCase().includes(q) ||
        r.pushname?.toLowerCase().includes(q) ||
        r.number?.includes(q)
    );
  }

  // Filter by date (from chats data)
  if (from) {
    const fromISO = new Date(from + "T00:00:00Z").toISOString();
    results = results.filter((r) => r.timestamp && r.timestamp >= fromISO);
  }

  // Filter by type
  if (filter === "pinned") results = results.filter((r) => r.pinned);
  else if (filter === "unread") results = results.filter((r) => r.unreadCount > 0);
  else if (filter === "groups") results = results.filter((r) => r.isGroup);

  // Sort by most recent activity
  results.sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""));

  return results;
}

/**
 * Get cached messages for a chat. Cache-only — no API calls.
 * Resolves the chat name to an id via contacts/chats cache, then reads messages/{id}.json.
 */
export function getMessages(chatQuery, since) {
  const resolved = resolveContact(chatQuery);
  if (!resolved) return { messages: [], error: `No chat found matching "${chatQuery}". Sync first.` };

  let filePath = join(MESSAGES_DIR, `${resolved.id}.json`);
  let cached = readCache(filePath);

  // Fallback: contacts resolve to @c.us but message files use the live chat id (@lid).
  // Check chats cache for an alternative id when the primary one has no messages file.
  if (!cached) {
    const chatCache = readCache(CHATS_CACHE);
    if (chatCache?.data) {
      const rName = resolved.name?.toLowerCase();
      const alt = chatCache.data.find(
        (c) => c.id !== resolved.id && c.name?.toLowerCase() === rName
      );
      if (alt) {
        filePath = join(MESSAGES_DIR, `${alt.id}.json`);
        cached = readCache(filePath);
      }
    }
  }

  if (!cached) return { messages: [], chat: resolved.name, error: "No messages cached. Use whatsapp_sync with what=\"messages\" first." };

  const cutoff = since
    ? new Date(since)
    : new Date(Date.now() - 24 * 60 * 60 * 1000);
  const filtered = cached.filter((m) => new Date(m.timestamp) >= cutoff);

  return { chat: resolved.name, id: resolved.id, messages: filtered };
}

// ── Tags (cache-only) ─────────────────────────────────────────

/**
 * Read tags cache, seeding defaults on first access.
 * Shape: { tags: { [name]: { description } }, contacts: { [contactId]: [tagName] } }
 */
function readTags() {
  const cached = readCache(TAGS_CACHE);
  if (cached) return cached;
  const fresh = { tags: { ...DEFAULT_TAGS }, contacts: {} };
  writeCache(TAGS_CACHE, fresh);
  return fresh;
}

/**
 * Check if a query matches a name at word boundaries.
 * Each query word must match at least one whole word in the name.
 * "Casa" won't match "Casachagua", but "Javier" matches "Javier Eduardo Carbajal".
 */
function wordMatch(name, queryWords) {
  if (!name) return false;
  const nameWords = name.toLowerCase().split(/\s+/);
  return queryWords.every((qw) => nameWords.some((nw) => nw === qw));
}

/**
 * Resolve a contact or group query to an id using both caches.
 * Pass 1: exact full-name match. Pass 2: word-level match.
 * Returns { id, name } or null.
 */
function resolveContact(query) {
  const q = query.toLowerCase();
  const queryWords = q.split(/\s+/);

  // Search contacts cache — prefer @c.us over @lid (WhatsApp internal linked IDs)
  // because chat APIs and message files use @c.us format.
  const contacts = readCache(CONTACTS_CACHE);
  if (contacts) {
    const preferCus = (matches) => matches.find((c) => c.id.endsWith("@c.us")) || matches[0];

    // Pass 1: exact full-name match
    const exactAll = contacts.filter(
      (c) =>
        c.name?.toLowerCase() === q ||
        c.pushname?.toLowerCase() === q ||
        c.id === query
    );
    if (exactAll.length > 0) {
      const pick = preferCus(exactAll);
      return { id: pick.id, name: pick.name || pick.pushname || pick.number };
    }

    // Pass 2: word-level match (every query word must match a whole word in the name)
    const wordAll = contacts.filter(
      (c) => wordMatch(c.name, queryWords) || wordMatch(c.pushname, queryWords)
    );
    if (wordAll.length > 0) {
      const pick = preferCus(wordAll);
      return { id: pick.id, name: pick.name || pick.pushname || pick.number };
    }
  }

  // Search chats cache (for groups and contacts not in the contacts list)
  const chats = readCache(CHATS_CACHE);
  if (chats?.data) {
    const exact = chats.data.find(
      (c) => c.name?.toLowerCase() === q || c.id === query
    );
    if (exact) return { id: exact.id, name: exact.name };

    const word = chats.data.find((c) => wordMatch(c.name, queryWords));
    if (word) return { id: word.id, name: word.name };
  }

  return null;
}

/**
 * Find candidate contacts/chats when a multi-word query fails exact resolution.
 * Splits the query into words and finds entries where ANY word matches a whole name word.
 * Returns an array of { id, name } candidates.
 */
function findCandidates(query) {
  const words = query.toLowerCase().split(/\s+/);
  const candidates = [];
  const seenIds = new Set();
  const seenNames = new Set();

  function addCandidate(id, name) {
    if (seenIds.has(id) || seenNames.has(name)) return;
    seenIds.add(id);
    seenNames.add(name);
    candidates.push({ id, name });
  }

  const contacts = readCache(CONTACTS_CACHE);
  if (contacts) {
    for (const c of contacts) {
      const nameWords = (c.name || "").toLowerCase().split(/\s+/);
      const pushnameWords = (c.pushname || "").toLowerCase().split(/\s+/);
      const allWords = [...nameWords, ...pushnameWords];
      if (words.some((w) => allWords.some((nw) => nw === w))) {
        addCandidate(c.id, c.name || c.pushname || c.number);
      }
    }
  }

  const chats = readCache(CHATS_CACHE);
  if (chats?.data) {
    for (const c of chats.data) {
      const nameWords = (c.name || "").toLowerCase().split(/\s+/);
      if (words.some((w) => nameWords.some((nw) => nw === w))) {
        addCandidate(c.id, c.name);
      }
    }
  }

  return candidates;
}

/**
 * Add tags to a contact. Creates new tags automatically if they don't exist.
 * `contact` is a name/number/id query, `tags` is an array of tag names.
 */
export function tagContact(contact, tags) {
  const resolved = resolveContact(contact);
  if (!resolved) {
    const words = contact.split(/\s+/);
    if (words.length > 1) {
      const candidates = findCandidates(contact);
      if (candidates.length > 0) {
        return { candidates: candidates.map((c) => c.name), query: contact };
      }
    }
    return { error: `No contact found matching "${contact}". Sync contacts first.` };
  }

  const data = readTags();
  for (const tag of tags) {
    if (!data.tags[tag]) data.tags[tag] = { description: null };
  }
  const existing = data.contacts[resolved.id] || [];
  const merged = [...new Set([...existing, ...tags])];
  data.contacts[resolved.id] = merged;
  writeCache(TAGS_CACHE, data);
  return { contact: resolved.name, id: resolved.id, tags: merged };
}

/**
 * Remove tags from a contact.
 */
export function untagContact(contact, tags) {
  const resolved = resolveContact(contact);
  if (!resolved) return { error: `No contact found matching "${contact}". Sync contacts first.` };

  const data = readTags();
  const existing = data.contacts[resolved.id] || [];
  const remaining = existing.filter((t) => !tags.includes(t));
  if (remaining.length === 0) {
    delete data.contacts[resolved.id];
  } else {
    data.contacts[resolved.id] = remaining;
  }
  writeCache(TAGS_CACHE, data);
  return { contact: resolved.name, id: resolved.id, tags: remaining };
}

/**
 * Get all tags for a specific contact.
 */
export function getContactTags(contact) {
  const resolved = resolveContact(contact);
  if (!resolved) return null;
  const data = readTags();
  return data.contacts[resolved.id] || [];
}

// ── Chat resolution & message fetching (API — used by syncMessages) ──

/**
 * Find a chat by name or phone number.
 * Resolves name → id from cache, then fetches the single live chat object via
 * getChatById() (one lightweight Puppeteer call) instead of getChats() which
 * serializes ALL chats. Falls back to getChats() only when cache is empty.
 */
export async function findChat(query) {
  try {
    // Try cache first — resolve name to id locally
    const cached = readCache(CHATS_CACHE);
    if (cached) {
      const q = query.toLowerCase();
      const match = cached.data.find(
        (c) => c.name?.toLowerCase() === q || c.id === query
      ) || cached.data.find(
        (c) => c.name?.toLowerCase().includes(q)
      );
      if (match) {
        // Fetch the single live chat object by id — one Puppeteer call, not all chats
        console.error(`[whatsapp] findChat: cache hit for "${query}" → id=${match.id}`);
        const live = await withReconnect(() => client.getChatById(match.id));
        if (!live) console.error(`[whatsapp] findChat: getChatById returned nothing for id=${match.id}`);
        return live || null;
      }
    }

    // No cache or no match — fall back to full getChats() (rare: only when cache is empty)
    console.error(`[whatsapp] findChat: cache miss for "${query}", falling back to getChats()...`);
    const chats = await withReconnect(() => client.getChats());
    const q = query.toLowerCase();

    let chat = chats.find((c) => {
      try { return c.name?.toLowerCase() === q || c.id._serialized === query || c.id.user === query; } catch { return false; }
    });
    if (!chat) {
      chat = chats.find((c) => { try { return c.name?.toLowerCase().includes(q); } catch { return false; } });
    }
    return chat || null;
  } catch (err) {
    console.error(`[whatsapp] findChat("${query}") failed: ${err.message}`);
    throw err;
  }
}

/**
 * Get messages from a chat.
 * Returns formatted message objects with id, sender, body, timestamp, etc.
 */
export async function getChatMessages(chat, limit = 50) {
  console.error(`[whatsapp] getChatMessages: fetching ${limit} msgs for "${chat.name}" (${chat.id._serialized})...`);
  const messages = await withReconnect(() => chat.fetchMessages({ limit }));
  console.error(`[whatsapp] getChatMessages: got ${messages.length} msgs, resolving contacts...`);

  // Resolve sender names from local contacts cache first (no API calls),
  // falling back to msg.getContact() only for unknown senders.
  // In group chats msg.from is the group id — use msg.author (individual sender) instead.
  const mentionMap = getMentionMap();
  const contactCache = {};
  const formatted = [];
  for (const msg of messages) {
    try {
      const senderId = msg.author || msg.from;
      if (!contactCache[senderId]) {
        // Try cache first — the number portion of senderId maps to a name
        const num = senderId.split("@")[0];
        const cachedName = mentionMap[num];
        if (cachedName) {
          contactCache[senderId] = cachedName;
        } else {
          // Cache miss — fall back to API (rare for known contacts)
          const contact = await withReconnect(() => msg.getContact());
          contactCache[senderId] = contact.pushname || contact.name || senderId;
        }
      }
      formatted.push({
        id: msg.id._serialized,
        sender: contactCache[senderId],
        from: senderId,
        body: msg.body,
        timestamp: new Date(msg.timestamp * 1000).toISOString(),
        type: msg.type,
        hasMedia: msg.hasMedia,
        isForwarded: msg.isForwarded,
        hasQuotedMsg: msg.hasQuotedMsg,
      });
    } catch (err) {
      console.error(`[whatsapp] getChatMessages: skipping msg (type=${msg.type}, from=${msg.from}): ${err.message}`);
    }
  }

  return formatted;
}

/**
 * Get group metadata (participants, description, owner).
 */
export async function getGroupInfo(chat) {
  assertReady();
  if (!chat.isGroup) return null;

  const participants = await chat.participants;

  return {
    name: chat.name,
    description: chat.description || null,
    participantCount: participants?.length || 0,
    participants:
      participants?.flatMap((p) => {
        try { return [{ id: p.id._serialized, isAdmin: p.isAdmin, isSuperAdmin: p.isSuperAdmin }]; }
        catch { return []; }
      }) || [],
  };
}

// ── Write helpers (commented out for later) ───────────────────

export async function sendMessage(chatId, text) {
  assertReady();
  return await withReconnect(() => client.sendMessage(chatId, text));
}

export async function replyToMessage(messageId, text) {
  assertReady();
  const target = await withReconnect(() => client.getMessageById(messageId));
  if (!target) throw new Error(`Message ${messageId} not found`);
  return await withReconnect(() => target.reply(text));
}

export async function reactToMessage(messageId, emoji) {
  assertReady();
  const target = await withReconnect(() => client.getMessageById(messageId));
  if (!target) throw new Error(`Message ${messageId} not found`);
  return await withReconnect(() => target.react(emoji));
}

export async function deleteMessage(messageId) {
  assertReady();
  const target = await withReconnect(() => client.getMessageById(messageId));
  if (!target) throw new Error(`Message ${messageId} not found`);
  return await withReconnect(() => target.delete(true));
}
