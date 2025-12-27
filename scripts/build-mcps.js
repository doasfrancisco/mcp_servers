const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT_DIR = path.join(__dirname, "..");
const SERVERS_DIR = path.join(ROOT_DIR, "servers");

const serverDirs = fs
  .readdirSync(SERVERS_DIR, { withFileTypes: true })
  .filter((dirent) => dirent.isDirectory())
  .map((dirent) => dirent.name);

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
    // Run npm install
    console.log("Running npm install...");
    execSync("npm install", { cwd: serverPath, stdio: "inherit" });

    // Run npm run build
    console.log("Running npm run build...");
    execSync("npm run build", { cwd: serverPath, stdio: "inherit" });

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
