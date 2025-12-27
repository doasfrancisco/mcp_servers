const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT_DIR = __dirname;
const CLAUDE_CODE_CONFIG_DIR = path.join(ROOT_DIR, "config", "claude-code");
const IS_WINDOWS = process.platform === "win32";
const SHELL = IS_WINDOWS ? "pwsh" : "/bin/bash";

console.log("===================================");
console.log("Add MCP Servers to Claude Code");
console.log("===================================\n");

// Step 1: Get list of currently added MCP servers
console.log("Checking currently added MCP servers...");
console.log("-----------------------------------");

let existingServers = [];
try {
  const listOutput = execSync("claude mcp list", { encoding: "utf-8" });
  console.log(listOutput);

  // Parse the output to extract server names
  // Format: "resend: node C:/... - ✓ Connected"
  const lines = listOutput.split("\n");
  for (const line of lines) {
    const match = line.match(/^(\w+):/);
    if (match) {
      existingServers.push(match[1]);
    }
  }
} catch (error) {
  console.log("No MCP servers currently configured.\n");
}

console.log(`Found ${existingServers.length} existing server(s): ${existingServers.join(", ") || "none"}\n`);

// Step 2: Get list of generated server configs
console.log("Checking available server configs...");
console.log("-----------------------------------");

const generatedFiles = fs
  .readdirSync(CLAUDE_CODE_CONFIG_DIR)
  .filter((file) => file.startsWith("generated-") && file.endsWith(".json"));

if (generatedFiles.length === 0) {
  console.log("No generated config files found.");
  console.log("Run 'node generate-config.js' first.");
  process.exit(1);
}

// Extract server names from filenames (generated-resend.json -> resend)
const availableServers = generatedFiles.map((file) =>
  file.replace("generated-", "").replace(".json", "")
);

console.log(`Found ${availableServers.length} available server(s): ${availableServers.join(", ")}\n`);

// Step 3: Add servers that aren't already added
console.log("Adding MCP servers...");
console.log("-----------------------------------");

let addedCount = 0;
let skippedCount = 0;

for (const serverName of availableServers) {
  if (existingServers.includes(serverName)) {
    console.log(`⏭  ${serverName} - already added, skipping`);
    skippedCount++;
    continue;
  }

  const configPath = path.join(CLAUDE_CODE_CONFIG_DIR, `generated-${serverName}.json`).replace(/\\/g, "/");

  try {
    execSync(`claude mcp add-json ${serverName} "$(cat ${configPath})" --scope user`, {
      encoding: "utf-8",
      stdio: "inherit",
      shell: SHELL,
    });
    console.log(`✓  ${serverName} - added successfully`);
    addedCount++;
  } catch (error) {
    console.error(`✗  ${serverName} - failed to add: ${error.message}`);
  }
}

console.log("\n===================================");
console.log(`Done! Added: ${addedCount}, Skipped: ${skippedCount}`);
console.log("===================================");
