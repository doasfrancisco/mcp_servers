/**
 * cache.js — JSON cache operations for contacts, chats, messages, and tags.
 *
 * Extracted from the original whatsapp_client.js. Same file structure,
 * same merge strategies, same data format — so existing cache files work.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { join } from "path";

const DATA_DIR = "C:/Francisco/github-repositories/mcp_servers/mcps/whatsapp";
export const CONTACTS_CACHE = join(DATA_DIR, "contacts.json");
export const CHATS_CACHE = join(DATA_DIR, "chats.json");
export const TAGS_CACHE = join(DATA_DIR, "tags.json");
export const MESSAGES_DIR = join(DATA_DIR, "messages");

const DEFAULT_TAGS = {
  family: { description: "Family members" },
  work: { description: "Work and professional contacts" },
  partner: { description: "Partner" },
  followup: { description: "Follow-ups and things to track" },
};

// ── Low-level cache I/O ───────────────────────────────────────

export function readCache(path) {
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf-8"));
}

export function writeCache(path, data) {
  try {
    writeFileSync(path, JSON.stringify(data, null, 2));
  } catch {}
}

// ── Mention map ───────────────────────────────────────────────

/** Build a number → contact name map for resolving @mentions.
 *  Maps both phone numbers (@c.us) and internal IDs (@lid) so mentions resolve regardless of format. */
export function getMentionMap() {
  const map = {};

  // From contacts cache (@c.us entries with phone numbers)
  const contacts = readCache(CONTACTS_CACHE) || [];
  for (const c of contacts) {
    const name = c.name || c.pushname || null;
    if (!name) continue;
    const num = c.id.split("@")[0];
    if (num && !map[num]) map[num] = name;
    if (c.number && !map[c.number]) map[c.number] = name;
  }

  // From chats cache (@lid entries that contacts cache doesn't have)
  const chatCache = readCache(CHATS_CACHE);
  if (chatCache?.data) {
    for (const c of chatCache.data) {
      if (!c.name || c.id.endsWith("@g.us") || c.id.endsWith("@broadcast")) continue;
      const num = c.id.split("@")[0];
      if (num && !map[num]) map[num] = c.name;
    }
  }

  return map;
}

// ── Chat resolution (by name, from chats cache) ──────────────
// The chats cache has the actual IDs the Chat store uses (@lid or @g.us).
// This mirrors the old whatsapp-web.js findChat() which searched chats by name first.

/** Resolve a chat name to { id, name } using the chats cache. Exact match only. */
export function resolveChatByName(query) {
  const chats = readCache(CHATS_CACHE);
  if (!chats?.data) return null;
  const q = query.toLowerCase();

  const exact = chats.data.find((c) => c.name?.toLowerCase() === q || c.id === query);
  if (exact) return { id: exact.id, name: exact.name };

  return null;
}

// ── Contact resolution ────────────────────────────────────────

function wordMatch(name, queryWords) {
  if (!name) return false;
  const nameWords = name.toLowerCase().split(/\s+/);
  return queryWords.every((qw) => nameWords.some((nw) => nw === qw));
}

/** Resolve a contact/group query to { id, name } using caches. */
export function resolveContact(query) {
  const q = query.toLowerCase();
  const queryWords = q.split(/\s+/);

  const contacts = readCache(CONTACTS_CACHE);
  if (contacts) {
    const preferCus = (matches) => matches.find((c) => c.id.endsWith("@c.us")) || matches[0];

    const exactAll = contacts.filter(
      (c) => c.name?.toLowerCase() === q || c.pushname?.toLowerCase() === q || c.id === query
    );
    if (exactAll.length > 0) {
      const pick = preferCus(exactAll);
      return { id: pick.id, name: pick.name || pick.pushname || pick.number };
    }

    const wordAll = contacts.filter(
      (c) => wordMatch(c.name, queryWords) || wordMatch(c.pushname, queryWords)
    );
    if (wordAll.length > 0) {
      const pick = preferCus(wordAll);
      return { id: pick.id, name: pick.name || pick.pushname || pick.number };
    }
  }

  const chats = readCache(CHATS_CACHE);
  if (chats?.data) {
    const exact = chats.data.find((c) => c.name?.toLowerCase() === q || c.id === query);
    if (exact) return { id: exact.id, name: exact.name };

    const word = chats.data.find((c) => wordMatch(c.name, queryWords));
    if (word) return { id: word.id, name: word.name };
  }

  return null;
}

/** Find candidate contacts when exact resolution fails. */
export function findCandidates(query) {
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

// ── Contacts sync ─────────────────────────────────────────────

const CONTACT_TRACKED_FIELDS = ["name", "pushname", "number"];

/** Merge fresh contacts into cache, tracking changes. */
export function mergeContacts(freshContacts) {
  const cached = readCache(CONTACTS_CACHE);
  if (!cached) {
    writeCache(CONTACTS_CACHE, freshContacts);
    return { synced: freshContacts.length, added: freshContacts.length, changed: 0 };
  }

  const cacheIndex = Object.fromEntries(cached.map((c) => [c.id, c]));
  let added = 0;
  let changed = 0;

  const merged = freshContacts.map((fc) => {
    const old = cacheIndex[fc.id];
    if (!old) { added++; return fc; }

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
  return { synced: merged.length, added, changed };
}

// ── Chats sync ────────────────────────────────────────────────

const CHAT_TRACKED_FIELDS = ["name"];

/** Merge fresh chats into cache, tracking changes. */
export function mergeChats(freshChats) {
  const cached = readCache(CHATS_CACHE);
  if (!cached) {
    const result = { lastRefresh: new Date().toISOString(), data: freshChats };
    writeCache(CHATS_CACHE, result);
    return { synced: freshChats.length, added: freshChats.length, changed: 0, updated: 0, updatedChats: [] };
  }

  const cacheIndex = Object.fromEntries(cached.data.map((c) => [c.id, c]));
  let added = 0;
  let changed = 0;
  const updatedChats = [];

  const merged = freshChats.map((fc) => {
    const old = cacheIndex[fc.id];
    if (!old) { added++; return fc; }

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

    if (fc.timestamp !== old.timestamp || fc.unreadCount !== old.unreadCount) {
      updatedChats.push({ name: fc.name, id: fc.id, archived: fc.archived, unreadCount: fc.unreadCount });
    }

    return fc;
  });

  const result = { lastRefresh: new Date().toISOString(), data: merged };
  writeCache(CHATS_CACHE, result);
  return { synced: merged.length, added, changed, updated: updatedChats.length, updatedChats };
}

// ── Messages sync ─────────────────────────────────────────────

/** Merge fetched messages into per-chat cache file. */
export function mergeMessages(chatId, freshMessages) {
  if (!existsSync(MESSAGES_DIR)) mkdirSync(MESSAGES_DIR);
  const filePath = join(MESSAGES_DIR, `${chatId}.json`);
  const existing = readCache(filePath) || [];

  const index = Object.fromEntries(existing.map((m) => [m.id, m]));
  for (const m of freshMessages) index[m.id] = m;
  const merged = Object.values(index).sort((a, b) => a.timestamp.localeCompare(b.timestamp));

  writeCache(filePath, merged);
  return { total: merged.length, added: merged.length - existing.length };
}

// ── Read messages (cache-only) ────────────────────────────────

/** Get cached messages for a chat. */
export function getMessages(chatQuery, since) {
  const resolved = resolveContact(chatQuery);
  if (!resolved) return { messages: [], error: `No chat found matching "${chatQuery}". Sync first.` };

  let filePath = join(MESSAGES_DIR, `${resolved.id}.json`);
  let cached = readCache(filePath);

  // Fallback: check chats cache for alternative id (@c.us vs @lid)
  if (!cached) {
    const chatCache = readCache(CHATS_CACHE);
    if (chatCache?.data) {
      const rName = resolved.name?.toLowerCase();
      const alt = chatCache.data.find((c) => c.id !== resolved.id && c.name?.toLowerCase() === rName);
      if (alt) {
        filePath = join(MESSAGES_DIR, `${alt.id}.json`);
        cached = readCache(filePath);
      }
    }
  }

  if (!cached) return { messages: [], chat: resolved.name, error: 'No messages cached. Use whatsapp_sync with what="messages" first.' };

  const cutoff = since ? new Date(since) : new Date(Date.now() - 24 * 60 * 60 * 1000);
  const filtered = cached.filter((m) => new Date(m.timestamp) >= cutoff);

  return { chat: resolved.name, id: resolved.id, messages: filtered };
}

// ── Find (cache-only search) ──────────────────────────────────

/** Unified search across contacts and chats caches. */
export function find({ query, tag, from, filter } = {}) {
  if (!query && !tag && !from && !filter) {
    const now = new Date();
    from = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }

  const tagData = readTags();
  const contacts = readCache(CONTACTS_CACHE) || [];
  const chatCache = readCache(CHATS_CACHE);
  const chats = chatCache?.data || [];

  const index = {};
  for (const c of contacts) index[c.id] = { ...c, tags: tagData.contacts[c.id] || [] };
  for (const c of chats) {
    if (index[c.id]) {
      Object.assign(index[c.id], {
        timestamp: c.timestamp, unreadCount: c.unreadCount,
        archived: c.archived, pinned: c.pinned,
        lastMessage: c.lastMessage, participants: c.participants,
      });
    } else {
      index[c.id] = { ...c, tags: tagData.contacts[c.id] || [] };
    }
  }

  let results = Object.values(index);

  if (tag) results = results.filter((r) => r.tags.includes(tag));
  if (query) {
    const q = query.toLowerCase();
    results = results.filter(
      (r) => r.name?.toLowerCase().includes(q) || r.pushname?.toLowerCase().includes(q) || r.number?.includes(q)
    );
  }
  if (from) {
    const fromISO = new Date(from + "T00:00:00Z").toISOString();
    results = results.filter((r) => r.timestamp && r.timestamp >= fromISO);
  }
  if (filter === "pinned") results = results.filter((r) => r.pinned);
  else if (filter === "unread") results = results.filter((r) => r.unreadCount > 0);
  else if (filter === "groups") results = results.filter((r) => r.isGroup);

  results.sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""));
  return results;
}

// ── Tags ──────────────────────────────────────────────────────

function readTags() {
  const cached = readCache(TAGS_CACHE);
  if (cached) return cached;
  const fresh = { tags: { ...DEFAULT_TAGS }, contacts: {} };
  writeCache(TAGS_CACHE, fresh);
  return fresh;
}

export function tagContact(contact, tags) {
  const resolved = resolveContact(contact);
  if (!resolved) {
    const words = contact.split(/\s+/);
    if (words.length > 1) {
      const candidates = findCandidates(contact);
      if (candidates.length > 0) return { candidates: candidates.map((c) => c.name), query: contact };
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

export function untagContact(contact, tags) {
  const resolved = resolveContact(contact);
  if (!resolved) return { error: `No contact found matching "${contact}". Sync contacts first.` };

  const data = readTags();
  const existing = data.contacts[resolved.id] || [];
  const remaining = existing.filter((t) => !tags.includes(t));
  if (remaining.length === 0) delete data.contacts[resolved.id];
  else data.contacts[resolved.id] = remaining;
  writeCache(TAGS_CACHE, data);
  return { contact: resolved.name, id: resolved.id, tags: remaining };
}
