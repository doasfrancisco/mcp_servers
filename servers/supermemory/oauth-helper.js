const http = require("http");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const AUTH_METADATA_URL = "https://api.supermemory.ai/.well-known/oauth-authorization-server";
const CALLBACK_PORT = 15068;
const REDIRECT_URI = `http://localhost:${CALLBACK_PORT}/callback`;

// Save tokens in this directory (gitignored)
const TOKENS_FILE = path.join(__dirname, ".tokens.json");

function generatePKCE() {
  const verifier = crypto.randomBytes(32).toString("base64url");
  const challenge = crypto.createHash("sha256").update(verifier).digest("base64url");
  return { verifier, challenge };
}

async function main() {
  console.log("Supermemory OAuth Setup");
  console.log("=======================\n");

  // Step 1: Fetch OAuth metadata
  console.log("1. Fetching OAuth metadata...");
  const metadataRes = await fetch(AUTH_METADATA_URL);
  const metadata = await metadataRes.json();
  console.log("   Authorization endpoint:", metadata.authorization_endpoint);
  console.log("   Token endpoint:", metadata.token_endpoint);

  // Step 2: Register client
  console.log("\n2. Registering OAuth client...");
  const regRes = await fetch(metadata.registration_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_name: "mcp-supermemory-proxy",
      redirect_uris: [REDIRECT_URI],
      grant_types: ["authorization_code", "refresh_token"],
      response_types: ["code"],
      token_endpoint_auth_method: "none",
    }),
  });
  const clientInfo = await regRes.json();
  console.log("   Client ID:", clientInfo.client_id);

  // Step 3: Generate PKCE
  const pkce = generatePKCE();

  // Step 4: Build authorization URL
  const authUrl = new URL(metadata.authorization_endpoint);
  authUrl.searchParams.set("response_type", "code");
  authUrl.searchParams.set("client_id", clientInfo.client_id);
  authUrl.searchParams.set("redirect_uri", REDIRECT_URI);
  authUrl.searchParams.set("code_challenge", pkce.challenge);
  authUrl.searchParams.set("code_challenge_method", "S256");
  authUrl.searchParams.set("scope", "openid profile email offline_access");
  authUrl.searchParams.set("prompt", "consent");

  console.log("\n3. Starting callback server on port", CALLBACK_PORT);

  // Step 5: Wait for OAuth callback
  const authCode = await new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url, `http://localhost:${CALLBACK_PORT}`);

      if (url.pathname === "/callback") {
        const code = url.searchParams.get("code");
        const error = url.searchParams.get("error");

        if (error) {
          res.writeHead(400, { "Content-Type": "text/html" });
          res.end(`<h1>Error: ${error}</h1><p>${url.searchParams.get("error_description")}</p>`);
          server.close();
          reject(new Error(error));
          return;
        }

        if (code) {
          res.writeHead(200, { "Content-Type": "text/html" });
          res.end("<h1>Success!</h1><p>You can close this window.</p>");
          server.close();
          resolve(code);
          return;
        }
      }

      res.writeHead(404);
      res.end("Not found");
    });

    server.listen(CALLBACK_PORT, () => {
      console.log("\n4. Opening browser for authentication...");

      const openCmd =
        process.platform === "win32" ? "start" : process.platform === "darwin" ? "open" : "xdg-open";
      try {
        execSync(`${openCmd} "${authUrl.toString()}"`, { stdio: "ignore", shell: true });
      } catch {
        console.log("\n   Could not open browser. Please open manually:");
        console.log("   " + authUrl.toString());
      }
    });

    setTimeout(() => {
      server.close();
      reject(new Error("Timeout (5 min)"));
    }, 5 * 60 * 1000);
  });

  console.log("\n5. Exchanging code for tokens...");

  // Step 6: Exchange code for tokens
  const tokenRes = await fetch(metadata.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code: authCode,
      redirect_uri: REDIRECT_URI,
      client_id: clientInfo.client_id,
      code_verifier: pkce.verifier,
    }),
  });

  if (!tokenRes.ok) {
    throw new Error(`Token exchange failed: ${tokenRes.status} ${await tokenRes.text()}`);
  }

  const tokens = await tokenRes.json();

  // Save combined data
  const data = {
    client_id: clientInfo.client_id,
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token,
    created_at: new Date().toISOString(),
  };

  fs.writeFileSync(TOKENS_FILE, JSON.stringify(data, null, 2));

  console.log("\n✅ OAuth setup complete!");
  console.log("   Tokens saved to:", TOKENS_FILE);
}

main().catch((err) => {
  console.error("\n❌ Error:", err.message);
  process.exit(1);
});
