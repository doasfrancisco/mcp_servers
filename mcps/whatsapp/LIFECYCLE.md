# WhatsApp MCP — Full Lifecycle Reference

End-to-end documentation of how the WhatsApp MCP server starts, connects to WhatsApp, handles failures, and recovers. Covers every layer: Claude Code → MCP transport → Express server → WhatsApp client → Puppeteer → Chrome → WhatsApp Web.

## Architecture overview

```
Claude Code (AI)
    │
    │  HTTP POST/GET/DELETE  (MCP protocol over StreamableHTTP)
    ▼
Express server  (server.js, port 39571)
    │
    │  createServer() per MCP session — tools are stateless
    ▼
wa.* module  (whatsapp_client.js)
    │
    │  Puppeteer CDP (Chrome DevTools Protocol over WebSocket)
    ▼
Chrome  (headless or visible, launched by Puppeteer)
    │
    │  HTTPS to web.whatsapp.com
    ▼
WhatsApp Web  (runs inside Chrome, manages stores via JS injection)
    │
    │  WhatsApp protocol (encrypted, via phone bridge)
    ▼
WhatsApp servers
```

## 1. Server startup

### How the server is launched

Claude Code's `SessionStart` hook in `~/.claude/settings.json`:

```bash
curl -sf http://localhost:39571/health > /dev/null 2>&1 || \
  (nohup node --watch C:/Francisco/.../mcps/whatsapp/server.js > /dev/null 2>&1 & \
   sleep 2 && echo 'WhatsApp MCP server started on port 39571')
```

- Checks `/health` first — only starts if server isn't already running.
- Uses `node --watch` — auto-restarts on ANY imported file change (including `whatsapp_client.js`).
- Runs in background (`nohup ... &`), persists across sessions.

### `main()` (server.js:280)

```js
async function main() {
  wa.killOrphanedChrome();   // 1. Kill leftover Chrome from previous crashes
  wa.init();                 // 2. Create WhatsApp client + start Chrome
  // ... Express setup ...
  app.listen(PORT);          // 3. Start HTTP server
}
```

**Critical: `wa.init()` is synchronous.** It creates the client and calls `client.initialize()` (fire-and-forget — the promise is not awaited). The Express server starts listening BEFORE the WhatsApp client is ready. Tool calls that arrive during initialization hit `assertReady()` and get "WhatsApp client is initializing — try again in ~15 seconds."

### Claude Code MCP config (`~/.claude.json`)

```json
{
  "whatsapp": {
    "type": "http",
    "url": "http://localhost:39571/mcp"
  }
}
```

HTTP transport — Claude Code connects via HTTP, not stdio. The server process is long-lived and shared across all Claude Code sessions.

## 2. WhatsApp client initialization

### `init()` (whatsapp_client.js:71)

```js
export function init() {
  if (client) return client;           // Idempotent — returns existing client

  const hasSession = existsSync(AUTH_MARKER);  // .wwebjs_auth/.authenticated

  client = new Client({
    authStrategy: new LocalAuth({ dataPath: AUTH_DIR }),
    puppeteer: {
      headless: hasSession,            // Headless if we have a session, visible if QR needed
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
    webVersionCache: { type: "local", path: CACHE_DIR },
  });

  // Register event handlers (see section 3)
  client.on("qr", ...);
  client.on("authenticated", ...);
  client.on("auth_failure", ...);
  client.on("ready", ...);
  client.on("disconnected", ...);

  // Fire and forget — does NOT block
  client.initialize().catch((err) => {
    console.error("[whatsapp] Initialize error:", err.message);
    if (!ready && existsSync(AUTH_MARKER)) {
      reconnect();  // Only retry if we had a valid session (not QR-needed)
    }
  });

  return client;
}
```

### What `client.initialize()` does inside whatsapp-web.js

Source: `node_modules/whatsapp-web.js/src/Client.js:302`

```
initialize()
  │
  ├─ authStrategy.beforeBrowserInitialized()
  ├─ puppeteer.launch({headless, args})          → Chrome process starts
  ├─ page.setUserAgent(...), page.setBypassCSP(true)
  ├─ authStrategy.afterBrowserInitialized()
  ├─ initWebVersionCache()
  ├─ page.goto("https://web.whatsapp.com", {waitUntil:'load', timeout:0})
  │     ↑ timeout:0 means INFINITE wait — if WhatsApp Web doesn't load, hangs forever
  │
  ├─ inject()                                    → Sets up all browser-side callbacks
  │     ├─ Polls window.Debug?.VERSION for 30s   → throws 'auth timeout' if not found
  │     ├─ Checks AppState — is auth needed?
  │     │     ├─ UNPAIRED → register QR handler, wait for scan
  │     │     └─ Already paired → skip
  │     │
  │     ├─ Registers onAppStateHasSyncedEvent callback (THE KEY CALLBACK):
  │     │     1. emit 'authenticated'
  │     │     2. Inject Store modules (ExposeStore)
  │     │     3. Poll window.Store for 30s → throws 'ready timeout' if not found
  │     │     4. Create ClientInfo, InterfaceController
  │     │     5. attachEventListeners()
  │     │     6. emit 'ready'                    → THIS is what sets our ready=true
  │     │
  │     └─ Registers state change / logout listeners
  │
  ├─ page.on('framenavigated', ...) → re-injects on navigation (logout/reload)
  │
  └─ RESOLVES (the promise completes here, BEFORE 'ready' fires)
```

**The critical insight:** `initialize()` resolves after `inject()` sets up callbacks. It does NOT wait for `authenticated` or `ready`. Those events fire later from browser-side callbacks (`onAppStateHasSyncedEvent`). This means `initialize().catch()` only catches failures during browser launch, page navigation, and callback setup — NOT store loading failures.

### The AUTH_MARKER file

Path: `.wwebjs_auth/.authenticated`

- **Written** in the `authenticated` event handler (contains ISO timestamp).
- **Deleted** on `auth_failure` or when QR is received in headless mode (session expired).
- **Purpose:** Determines headless vs visible Chrome on next `init()`. The `LocalAuth` directory existing alone is NOT reliable — it's created before auth completes.

## 3. Event handlers and state machine

### Module-level state

```js
let client = null;           // The whatsapp-web.js Client instance
let readyTimer = null;       // setTimeout ID for ready timeout after auth

// Explicit state machine — replaces the old boolean flags (ready, reconnecting)
// that had race conditions when multiple disconnect triggers fired simultaneously.
const State = { INITIALIZING, READY, RECONNECTING, DEAD };
let state = State.INITIALIZING;
let reconnectAttempts = 0;   // Consecutive failures, resets on 'ready'
let lastReconnectTime = 0;   // Timestamp debounce to coalesce concurrent triggers
```

Transitions:
- `init()` called → `INITIALIZING`
- `ready` event → `READY` (resets `reconnectAttempts` and `lastReconnectTime`)
- `reconnect()` called → `RECONNECTING` (stays until `ready` fires or max attempts exceeded)
- Max attempts exceeded → `DEAD`

### Event: `qr`

Fires when WhatsApp Web shows a QR code for scanning.

```js
client.on("qr", (qr) => {
  if (hasSession) {
    // BUG CASE: We launched headless (marker existed) but session is expired.
    // WhatsApp wants a new QR but there's no visible browser to scan it.
    // Fix: delete marker, reconnect with visible browser.
    unlinkSync(AUTH_MARKER);
    reconnectAttempts = 0;    // Reset — this is a fresh auth flow, not a failure
    reconnect();
    return;
  }
  // Normal case: visible browser, user can scan
  console.error("[whatsapp] QR code received — scan with your phone");
  console.error(qr);
});
```

**Edge case — `hasSession` is a closure.** It captures the marker state at `init()` time. If the marker is deleted and `init()` is called again (via `reconnect()`), the NEW `init()` call gets a fresh `hasSession = false`.

### Event: `authenticated`

Fires when WhatsApp Web confirms the session (QR scanned or session restored).

```js
client.on("authenticated", () => {
  writeFileSync(AUTH_MARKER, new Date().toISOString());

  // START READY TIMEOUT — if 'ready' doesn't fire within 30s, stores are hung
  clearTimeout(readyTimer);
  readyTimer = setTimeout(() => {
    if (state !== State.READY) {
      console.error("[whatsapp] Ready timeout — stores never loaded, retrying");
      reconnect("ready_timeout");
    }
  }, READY_TIMEOUT_MS);  // 30_000
});
```

**Why this timeout exists:** Inside whatsapp-web.js, after `authenticated` fires, the library polls `window.Store` for 30s. If Store injection fails, it throws `'ready timeout'` — but that error is thrown inside a browser callback (`onAppStateHasSyncedEvent`), NOT in the `initialize()` promise chain. The error goes nowhere. Our 30s timer on the Node.js side catches this silent failure.

### Event: `auth_failure`

Fires when session restoration fails (corrupted session data, etc.).

```js
client.on("auth_failure", (msg) => {
  unlinkSync(AUTH_MARKER);      // Force QR on next attempt
  reconnectAttempts = 0;        // Reset — need fresh auth
  reconnect("auth_failure");
});
```

**Note:** whatsapp-web.js also calls `this.destroy()` and possibly `this.initialize()` internally on auth failure (Client.js:151-156). Our `reconnect("auth_failure")` initiates its own destroy — safe because the state machine prevents re-entry.

### Event: `ready`

Fires when WhatsApp Web is fully loaded — stores injected, event listeners attached.

```js
client.on("ready", () => {
  clearTimeout(readyTimer);
  state = State.READY;          // THE transition that gates all tool calls
  reconnectAttempts = 0;        // Reset consecutive failure counter
  lastReconnectTime = 0;        // Reset debounce so future reconnects aren't blocked
});
```

**This is the only place `state` becomes `READY`.** Everything gates on this via `assertReady()`.

### Event: `change_state`

Fires on every WhatsApp Web state transition (CONNECTED, OPENING, TIMEOUT, etc.). Logged for debugging — helps trace what happened before a disconnect.

```js
client.on("change_state", (waState) => {
  console.error(`[whatsapp] State changed: ${waState}`);
});
```

### Event: `disconnected`

Fires when WhatsApp Web enters a non-accepted state.

```js
client.on("disconnected", (reason) => {
  reconnect("disconnected_event");
});
```

**How it's triggered inside whatsapp-web.js (Client.js:603-632):**

```js
// Browser-side state change listener
const ACCEPTED_STATES = [CONNECTED, OPENING, PAIRING, TIMEOUT];
// If takeoverOnConflict: also CONFLICT

if (!ACCEPTED_STATES.includes(state)) {
  await this.authStrategy.disconnect();
  this.emit('disconnected', state);
  this.destroy();  // NOTE: called WITHOUT await
}
```

States that trigger disconnect: `CONFLICT`, `DEPRECATED_VERSION`, `PROXYBLOCK`, `SMB_TOS_BLOCK`, `TOS_BLOCK`, `UNLAUNCHED`, `UNPAIRED`, `UNPAIRED_IDLE`.

**Double-destroy prevention:** The library calls `this.destroy()` without `await` after emitting `disconnected`. Our handler passes `source="disconnected_event"` so `reconnect()` skips calling `client.destroy()` again — instead it waits 2s for the library's destroy to finish, then force-kills any remaining Chrome processes.

## 4. Reconnection

### `reconnect(source)` (whatsapp_client.js:180)

```js
async function reconnect(source = "unknown") {
  // State guard — replaces the old boolean `reconnecting` flag
  if (state === State.RECONNECTING || state === State.DEAD) return;

  // Timestamp debounce — a single disconnect fires multiple handlers
  // (withReconnect, disconnected event, ready timeout). Only let one through.
  if (Date.now() - lastReconnectTime < RECONNECT_DEBOUNCE_MS) return;

  reconnectAttempts++;
  if (reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
    state = State.DEAD;         // Only server restart recovers
    return;
  }

  state = State.RECONNECTING;   // Stays RECONNECTING until 'ready' fires
  lastReconnectTime = Date.now();

  if (client) {
    if (source === "disconnected_event") {
      // Library already called destroy() — wait briefly, then force-kill stragglers
      await sleep(2000);
      killOrphanedChrome();
    } else {
      // We initiate the destroy ourselves
      try {
        await Promise.race([client.destroy(), timeout(DESTROY_TIMEOUT_MS)]);
      } catch {
        killOrphanedChrome();
      }
    }
    client = null;
  }

  init();   // State stays RECONNECTING — 'ready' event transitions to READY
}
```

**Source parameter:** Each caller identifies itself so `reconnect()` can handle the double-destroy case. When `source="disconnected_event"`, the library already started destroying Chrome — we skip our own `destroy()` call and just force-kill stragglers after a brief wait.

**Debounce:** Prevents a single disconnect from burning multiple retry attempts. The `lastReconnectTime` check rejects duplicate triggers within 5 seconds. Resets on successful `ready`.

### What `client.destroy()` does (whatsapp-web.js Client.js:878)

```js
async destroy() {
  const browser = this.pupBrowser;
  const isConnected = browser?.isConnected?.();
  if (isConnected) {
    await browser.close();          // CDP call to Chrome — can hang if WebSocket is broken
  }
  await this.authStrategy.destroy();  // Cleanup auth strategy state
}
```

**When `destroy()` can't kill Chrome:**
- `isConnected()` checks if Puppeteer's WebSocket to Chrome is alive.
- If WebSocket is broken (Chrome crashed, network issue), `isConnected()` returns `false` → `browser.close()` is skipped → Chrome process stays alive.
- Our 10s timeout catches the case where `isConnected()` is true but `browser.close()` hangs (Chrome unresponsive but WebSocket alive).
- In both cases, `killOrphanedChrome()` force-kills the process.

### `killOrphanedChrome()` (whatsapp_client.js:39)

Finds Chrome processes with `.wwebjs_auth` in the command line and kills them.

- **Windows:** `wmic` to find PIDs, `taskkill /T /F` to kill the process tree.
- **Linux/Mac:** `pkill -f '.wwebjs_auth'`.
- Only matches root browser processes (no `--type=` flag) to avoid killing renderer subprocesses separately.

### When `killOrphanedChrome()` is called

| Caller | When |
|---|---|
| `main()` at startup | Always — cleans up from previous crashes / `--watch` restarts |
| `reconnect()` | Only when `client.destroy()` fails or times out |
| `shutdown()` handler | On SIGTERM/SIGINT — since graceful `destroy()` can hang on Windows |

**NOT called in `init()`** — was removed in commit a527f71 to avoid killing Chrome mid-transition during reconnect. The destroy timeout in `reconnect()` handles this instead.

## 5. MCP transport layer

### Session management (server.js:290-338)

Three cases when a POST hits `/mcp`:

**Case 1: Known session** (sessionId exists in `transports` map)
```
→ Route directly to that session's transport.handleRequest()
```

**Case 2: Initialize request** (new client connecting)
```
→ Create new StreamableHTTPServerTransport
→ Create new McpServer (createServer())
→ server.connect(transport)
→ Handle the request
```

**Case 3: Stale session** (sessionId present but not in map — server restarted)
```
→ Create new transport with the SAME sessionId
→ Create new McpServer
→ server.connect(transport)
→ Bypass SDK init handshake: transport._webStandardTransport._initialized = true
→ Handle the request
```

**Key point:** MCP sessions are transport-level constructs. The WhatsApp client is module-level singleton — ALL MCP sessions share the same `wa.*` functions and the same Chrome instance.

### What happens during Claude Code `/mcp` reconnect

1. Claude Code drops the HTTP connection.
2. User runs `/mcp` to reconnect.
3. Claude Code sends a new HTTP POST to `localhost:39571/mcp`.
4. If the server process is still running (it usually is — it's long-lived):
   - The old session ID is stale (not in `transports` map if the server restarted, or still there if it didn't).
   - Case 1 or Case 3 handles it.
5. The WhatsApp client state is **unchanged** — it's module-level, not tied to MCP sessions.
6. If `ready` is true, tool calls work immediately.
7. If `ready` is false (WhatsApp disconnected independently), tool calls fail with state-specific errors.

### What happens during `node --watch` restart

1. File change detected (e.g., editing `whatsapp_client.js`).
2. `node --watch` kills the old server process (SIGTERM on Linux, unconditional kill on Windows).
3. `shutdown()` handler calls `killOrphanedChrome()` — but on Windows, SIGTERM kills the process before the handler runs.
4. New server process starts: `main()` → `killOrphanedChrome()` → `init()` → Express starts.
5. Claude Code's next HTTP request hits the new server. Old session ID is stale → Case 3 handles it.
6. WhatsApp client is initializing — tool calls get "WhatsApp client is initializing" until `ready` fires.

## 6. Tool call flow

### API tools (require WhatsApp connection)

```
Claude Code calls whatsapp_sync
    │
    ▼
server.js tool handler
    │  try { await wa.syncAll() } catch { return error }
    ▼
wa.syncAll()
    │  assertReady()              ← Gates on ready flag
    │  Promise.allSettled([syncContacts(), syncChats()])
    ▼
wa.syncContacts() / wa.syncChats()
    │  assertReady()              ← Redundant but safe
    │  await withReconnect(() => client.getContacts())
    ▼
withReconnect(fn)
    │  Promise.race([fn(), timeout(30s)])
    │
    ├─ Success → return result
    ├─ Timeout → ready=false, reconnect(), throw "timed out"
    ├─ Detached frame → reconnect(), throw "session lost"
    ├─ Stores loading → throw "still loading"
    └─ Other error → throw as-is
```

### Cache-only tools (no WhatsApp connection needed)

`whatsapp_find`, `whatsapp_get_messages`, `whatsapp_tag_contacts` read from JSON cache files. They never call `assertReady()` or touch the WhatsApp API. They work even when Chrome is dead.

## 7. `assertReady()` — state-specific error messages

```js
function assertReady() {
  switch (state) {
    case State.READY:        return;  // OK
    case State.RECONNECTING: → "WhatsApp is reconnecting (attempt N/3) — try again in ~15 seconds."
    case State.DEAD:         → "WhatsApp reconnection failed after all retries. Restart the MCP server."
    case State.INITIALIZING: → "WhatsApp client is initializing — try again in ~15 seconds."
    default:                 → "WhatsApp client is not running. Restart the MCP server."
  }
}
```

## 8. Failure modes and recovery

### Failure: Chrome launched but stores never load

```
Timeline:
  authenticated fires → readyTimer starts (30s)
  ... 30 seconds pass, ready never fires ...
  readyTimer fires → reconnect()
  → destroy with 10s timeout → init() → new Chrome
  → if fails again: attempt 2/3, then 3/3, then gives up
```

Recovery: automatic (up to 3 attempts). After that, manual server restart.

### Failure: Chrome becomes unresponsive during operation

```
Timeline:
  ready = true (was working)
  Chrome hangs (page crash, memory, network)
  Tool call → assertReady() passes (ready still true)
  → withReconnect(fn) → Promise.race with 30s timeout
  → timeout fires → ready = false → reconnect()
```

Recovery: automatic. The 30s API timeout is the only thing that detects this — no whatsapp-web.js event fires for a zombied Chrome.

### Failure: `client.destroy()` hangs (CDP broken)

```
Timeline:
  reconnect() called
  → client.destroy() starts, CDP WebSocket broken
  → 10s timeout fires → killOrphanedChrome() → force-kills Chrome
  → client = null → init() → fresh start
```

Recovery: automatic via force-kill.

### Failure: `client.destroy()` skips browser.close() (Puppeteer disconnected)

```
Timeline:
  Chrome crashed → Puppeteer WebSocket broken
  → disconnected event fires → reconnect()
  → client.destroy() → isConnected() returns false → browser.close() SKIPPED
  → authStrategy.destroy() → destroy resolves quickly
  → But Chrome process may still be alive (zombie)
  → init() → new Chrome may conflict with old Chrome on same user-data-dir
```

Recovery: the new Chrome will either take over the user-data-dir (Chrome's single-instance behavior) or fail to initialize → `initialize().catch()` triggers reconnect → eventually `killOrphanedChrome()` in the destroy timeout path.

### Failure: Session expired (QR needed in headless mode)

```
Timeline:
  AUTH_MARKER exists → init() launches headless Chrome
  WhatsApp says "scan QR" → qr event fires
  → hasSession is true (marker existed at init time)
  → delete marker, reconnectAttempts = 0, reconnect()
  → destroy → init() → hasSession is now false → visible Chrome opens
  → QR code displayed, user scans → authenticated → ready
```

Recovery: automatic switch to visible browser. Counter reset so all 3 attempts are available.

### Failure: `initialize()` rejects early (browser crash, nav failure)

```
Timeline:
  init() → client.initialize() → puppeteer.launch() fails or page.goto() fails
  → .catch() fires → if AUTH_MARKER exists: reconnect()
  → if no AUTH_MARKER (QR needed): no reconnect, just log the error
```

The AUTH_MARKER guard prevents reconnect loops when the QR hasn't been scanned — each reconnect would launch a new visible Chrome asking for QR.

### Failure: Max reconnect attempts exhausted

```
State:
  reconnectAttempts = 3 (or more)
  reconnecting = false
  ready = false
  client = null (or stale)
```

`assertReady()` returns: "WhatsApp reconnection failed after all retries. Restart the MCP server to recover."

Recovery: manual only — restart the server process. `node --watch` restart (touch a file) or kill and relaunch.

### Failure: MCP transport reconnect while WhatsApp is healthy

```
Timeline:
  WhatsApp is ready = true
  Claude Code disconnects → reconnects via /mcp
  → HTTP POST with stale session ID → Case 3 in server.js
  → New MCP transport created, tools work immediately
  → WhatsApp state unchanged
```

No failure — this is the happy path. The confusion arises when WhatsApp disconnected independently during the same period.

## 9. Process management

### Shutdown (server.js:372)

```js
function shutdown() {
  wa.killOrphanedChrome();     // Force-kill, no CDP — can't trust graceful on Windows
  process.exit(0);
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
```

**Windows caveat:** SIGTERM kills the process unconditionally — the handler MAY NOT run. That's why `killOrphanedChrome()` runs at startup too.

### Constants

| Constant | Value | Purpose |
|---|---|---|
| `MAX_RECONNECT_ATTEMPTS` | 3 | Consecutive failures before giving up |
| `READY_TIMEOUT_MS` | 30,000 | Time after `authenticated` to wait for `ready` |
| `DESTROY_TIMEOUT_MS` | 10,000 | Time for graceful `client.destroy()` before force-kill |
| `API_TIMEOUT_MS` | 30,000 | Time for any API call before considering Chrome dead |
| `PORT` | 39571 | HTTP server port |

### File system artifacts

| Path | Purpose |
|---|---|
| `.wwebjs_auth/` | Puppeteer user-data-dir (Chrome profile, session data) |
| `.wwebjs_auth/.authenticated` | Marker file — presence means "session was valid, use headless" |
| `.wwebjs_cache/` | WhatsApp Web version cache |
| `contacts.json` | Cached contacts from last sync |
| `chats.json` | Cached chats from last sync |
| `tags.json` | User-created tags for contacts |
| `messages/` | Per-chat message cache files (`{chatId}.json`) |
