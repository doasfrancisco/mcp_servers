const fs = require("fs");
const path = require("path");

const ROOT_DIR = __dirname;
const CONFIG_DIR = path.join(ROOT_DIR, "config");
const ENV_FILE = path.join(ROOT_DIR, ".env");

console.log("===================================");
console.log("MCP Config Generator");
console.log("===================================\n");

// Check if .env exists
if (!fs.existsSync(ENV_FILE)) {
  console.error("Error: .env file not found!");
  console.error("Please copy .env.example to .env and fill in your API keys.");
  process.exit(1);
}

// Parse .env file
const envContent = fs.readFileSync(ENV_FILE, "utf-8");
const env = {};
for (const line of envContent.split("\n")) {
  const trimmed = line.trim();
  if (trimmed && !trimmed.startsWith("#")) {
    const [key, ...valueParts] = trimmed.split("=");
    if (key && valueParts.length > 0) {
      let value = valueParts.join("=").trim();
      // Strip surrounding quotes (single or double)
      if ((value.startsWith("'") && value.endsWith("'")) ||
          (value.startsWith('"') && value.endsWith('"'))) {
        value = value.slice(1, -1);
      }
      env[key.trim()] = value;
    }
  }
}

// Add the MCP_SERVERS_PATH (this repo's absolute path)
env.MCP_SERVERS_PATH = ROOT_DIR.replace(/\\/g, "/"); // Use forward slashes for all platforms

console.log("Loaded environment variables:");
for (const [key, value] of Object.entries(env)) {
  const displayValue = key.includes("KEY") ? value.substring(0, 8) + "..." : value;
  console.log(`  ${key}: ${displayValue}`);
}
console.log("");

// Get all client folders in config/
const clientFolders = fs
  .readdirSync(CONFIG_DIR, { withFileTypes: true })
  .filter((dirent) => dirent.isDirectory())
  .map((dirent) => dirent.name);

for (const clientFolder of clientFolders) {
  const clientDir = path.join(CONFIG_DIR, clientFolder);
  const templatePath = path.join(clientDir, "mcp-servers.json");

  if (!fs.existsSync(templatePath)) {
    console.log(`Skipping ${clientFolder} (no mcp-servers.json found)`);
    continue;
  }

  console.log(`Processing: ${clientFolder}`);
  console.log("-----------------------------------");

  // Read and parse template
  let templateContent = fs.readFileSync(templatePath, "utf-8");

  // Replace all {{VARIABLE}} placeholders
  for (const [key, value] of Object.entries(env)) {
    const placeholder = `{{${key}}}`;
    templateContent = templateContent.split(placeholder).join(value);
  }

  // Parse the filled template
  const config = JSON.parse(templateContent);
  const mcpServers = config.mcpServers || {};

  // Generate individual file for each server
  for (const [serverName, serverConfig] of Object.entries(mcpServers)) {
    const outputPath = path.join(clientDir, `generated-${serverName}.json`);
    const outputContent = JSON.stringify(serverConfig, null, 2);

    fs.writeFileSync(outputPath, outputContent);
    console.log(`  ✓ generated-${serverName}.json`);
  }

  console.log("");
}

console.log("===================================");
console.log("Config generation complete!");
console.log("===================================\n");

console.log("To add a server to Claude Code:");
console.log('  claude mcp add-json <name> "$(cat config/claude-code/generated-<name>.json)" --scope user');
console.log("");
console.log("Example:");
console.log('  claude mcp add-json resend "$(cat config/claude-code/generated-resend.json)" --scope user');
