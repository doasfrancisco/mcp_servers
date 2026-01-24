const { execSync, spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT_DIR = path.join(__dirname, "..");
const SERVERS_DIR = path.join(ROOT_DIR, "servers");

const serverDirs = fs
  .readdirSync(SERVERS_DIR, { withFileTypes: true })
  .filter((dirent) => dirent.isDirectory())
  .map((dirent) => dirent.name);

const skipServers = ["supermemory", "catafract", "crosspost"];

let successCount = 0;
let failCount = 0;

for (const serverName of serverDirs) {
  const serverPath = path.join(SERVERS_DIR, serverName);
  const packageJsonPath = path.join(serverPath, "package.json");

  // Skip if no package.json
  if (!fs.existsSync(packageJsonPath)) {
    console.log(`Skipping ${serverName} (no package.json)\n`);
    continue;
  }

  console.log(`Setting up: ${serverName}`);
  console.log("-----------------------------------");

  try {
    if (skipServers.includes(serverName)) {
      console.log(`Skipping ${serverName} (managed externally)\n`);
      continue;
    }
    // Run npm install
    console.log("Running npm install...");
    execSync("npm install", { cwd: serverPath, stdio: "inherit" });

    // Check if there's a build script
    const pkg = JSON.parse(fs.readFileSync(packageJsonPath, "utf-8"));
    if (pkg.scripts && pkg.scripts.build) {
      console.log("Running npm run build...");
      execSync("npm run build", { cwd: serverPath, stdio: "inherit" });
    }

    // Special handling for nia - uses pipx
    if (serverName === "nia") {
      console.log("Installing nia-mcp-server via pipx...");
      execSync("pipx install nia-mcp-server", { cwd: serverPath, stdio: "inherit" });
      console.log(`✓ ${serverName} ready\n`);
      successCount++;
      continue;
    }

    // Special handling for supermemory OAuth
    if (serverName === "supermemory") {
      const tokensFile = path.join(serverPath, ".tokens.json");
      if (!fs.existsSync(tokensFile)) {
        console.log("\nSupermemory requires OAuth authentication.");
        console.log("Running oauth-helper.js...\n");
        const result = spawnSync("node", ["oauth-helper.js"], {
          cwd: serverPath,
          stdio: "inherit",
        });
        if (result.status !== 0) {
          throw new Error("OAuth setup failed");
        }
      } else {
        console.log("OAuth tokens already exist, skipping authentication.");
      }
    }

    console.log(`✓ ${serverName} ready\n`);
    successCount++;
  } catch (error) {
    console.error(`✗ ${serverName} failed: ${error.message}\n`);
    failCount++;
  }
}

console.log("===================================");
console.log(`Setup complete! (${successCount} succeeded, ${failCount} failed)`);
console.log("===================================\n");

console.log("Next steps:");
console.log("1. Copy .env.example to .env");
console.log("2. Fill in your API keys in .env");
console.log("3. Run: node generate-config.js");
console.log("4. Copy the generated config to your MCP client");
