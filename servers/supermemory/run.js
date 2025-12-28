const fs = require("fs");
const path = require("path");
const readline = require("readline");

const SERVER_URL = "https://api.supermemory.ai/mcp";
const TOKEN_ENDPOINT = "https://api.supermemory.ai/api/auth/mcp/token";

// Token storage in this directory (gitignored)
const TOKENS_FILE = path.join(__dirname, ".tokens.json");

let currentAccessToken = null;
let sessionId = null;

function log(...args) {
  process.stderr.write("[supermemory] " + args.join(" ") + "\n");
}

async function getAccessToken() {
  if (!fs.existsSync(TOKENS_FILE)) {
    throw new Error("No saved tokens. Run: node servers/supermemory/oauth-helper.js");
  }

  const data = JSON.parse(fs.readFileSync(TOKENS_FILE, "utf8"));

  const response = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: data.refresh_token,
      client_id: data.client_id,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Token refresh failed: ${response.status} ${errorText}`);
  }

  const newTokens = await response.json();

  // Update stored tokens
  data.access_token = newTokens.access_token;
  if (newTokens.refresh_token) {
    data.refresh_token = newTokens.refresh_token;
  }

  fs.writeFileSync(TOKENS_FILE, JSON.stringify(data, null, 2));
  return data.access_token;
}

async function sendMcpRequest(message) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
    Authorization: `Bearer ${currentAccessToken}`,
  };

  if (sessionId) {
    headers["Mcp-Session-Id"] = sessionId;
  }

  const response = await fetch(SERVER_URL, {
    method: "POST",
    headers,
    body: JSON.stringify(message),
  });

  if (response.status === 401) {
    log("Token expired, refreshing...");
    currentAccessToken = await getAccessToken();
    return sendMcpRequest(message);
  }

  if (!response.ok) {
    const errText = await response.text();
    log("Server error:", response.status, errText.substring(0, 200));
    throw new Error(`MCP request failed: ${response.status}`);
  }

  // Capture session ID from response headers
  const newSessionId = response.headers.get("Mcp-Session-Id");
  if (newSessionId) {
    sessionId = newSessionId;
    log("Got session ID:", sessionId.substring(0, 20) + "...");
  }

  // Parse SSE response
  const text = await response.text();
  const lines = text.split("\n");

  for (const line of lines) {
    if (line.startsWith("data: ")) {
      const data = line.slice(6);
      if (data.trim()) {
        return JSON.parse(data);
      }
    }
  }

  // For notifications (no id), there might not be a data response
  if (!message.id) {
    return null;
  }

  throw new Error("No data in SSE response");
}

async function main() {
  log("Starting supermemory proxy");

  currentAccessToken = await getAccessToken();
  log("Token refreshed successfully");

  const rl = readline.createInterface({
    input: process.stdin,
    terminal: false,
  });

  // Queue to process requests sequentially
  const queue = [];
  let processing = false;
  let closing = false;

  async function processQueue() {
    if (processing || queue.length === 0) return;
    processing = true;

    while (queue.length > 0) {
      const line = queue.shift();
      try {
        const request = JSON.parse(line);
        const response = await sendMcpRequest(request);
        if (response) {
          console.log(JSON.stringify(response));
        }
      } catch (err) {
        log("Error:", err.message);
        let id = null;
        try {
          id = JSON.parse(line).id;
        } catch {}
        if (id !== undefined) {
          console.log(
            JSON.stringify({
              jsonrpc: "2.0",
              id: id,
              error: { code: -32603, message: err.message },
            })
          );
        }
      }
    }

    processing = false;
    if (closing) process.exit(0);
  }

  rl.on("line", (line) => {
    if (!line.trim()) return;
    log("Queued:", line.substring(0, 60) + "...");
    queue.push(line);
    processQueue();
  });

  rl.on("close", () => {
    closing = true;
    if (!processing && queue.length === 0) process.exit(0);
  });
}

main().catch((err) => {
  log("Fatal:", err.message);
  console.log(
    JSON.stringify({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32603, message: err.message },
    })
  );
  process.exit(1);
});
