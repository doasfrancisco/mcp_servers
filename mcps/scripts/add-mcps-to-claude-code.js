const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

const ROOT_DIR = path.join(__dirname, "..");
const CLAUDE_CODE_CONFIG_DIR = path.join(ROOT_DIR, "config", "claude-code");
const IS_WINDOWS = process.platform === "win32";
const SHELL = IS_WINDOWS ? "pwsh" : "/bin/bash";
const ignoreServers = ["nia-old"];

function getExistingServers() {
  try {
    const listOutput = execSync("claude mcp list", { encoding: "utf-8" });
    const lines = listOutput.split("\n");
    const servers = [];
    for (const line of lines) {
      const match = line.match(/^([\w-]+):/);
      if (match) {
        servers.push(match[1]);
      }
    }
    return servers;
  } catch (error) {
    return [];
  }
}

function getAvailableServers() {
  const generatedFiles = fs
    .readdirSync(CLAUDE_CODE_CONFIG_DIR)
    .filter((file) => file.startsWith("generated-") && file.endsWith(".json"));

  return generatedFiles.map((file) =>
    file.replace("generated-", "").replace(".json", "")
  );
}

function addServer(serverName) {
  const configPath = path.join(CLAUDE_CODE_CONFIG_DIR, `generated-${serverName}.json`).replace(/\\/g, "/");

  try {
    execSync(`claude mcp add-json ${serverName} "$(cat ${configPath})" --scope user`, {
      encoding: "utf-8",
      stdio: "inherit",
      shell: SHELL,
    });
    console.log(`✓  ${serverName} - added successfully\n`);
    return true;
  } catch (error) {
    console.error(`✗  ${serverName} - failed to add: ${error.message}\n`);
    return false;
  }
}

async function prompt(rl, question) {
  return new Promise((resolve) => {
    rl.question(question, resolve);
  });
}

async function main() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  console.log("===================================");
  console.log("Add MCP Servers to Claude Code");
  console.log("===================================\n");

  let addedCount = 0;

  while (true) {
    process.stdout.write("Fetching installed servers from Claude Code... ");
    const existingServers = getExistingServers();
    console.log("done.\n");

    const availableServers = getAvailableServers();

    // Filter to servers that can be installed
    const installableServers = availableServers.filter(
      (server) => !existingServers.includes(server) && !ignoreServers.includes(server)
    );

    // Show already installed servers
    if (existingServers.length > 0) {
      console.log("Already installed:");
      console.log("-----------------------------------");
      existingServers.forEach((server) => {
        console.log(`  ✓ ${server}`);
      });
      console.log("-----------------------------------\n");
    }

    if (installableServers.length === 0) {
      console.log("All available servers are already installed!");
      break;
    }

    console.log("Available to install:");
    console.log("-----------------------------------");
    installableServers.forEach((server, index) => {
      console.log(`  ${index + 1}. ${server}`);
    });
    console.log(`  0. Exit`);
    console.log("-----------------------------------");

    const answer = await prompt(rl, "Select a server to install (number): ");
    const choice = parseInt(answer.trim(), 10);

    if (choice === 0 || isNaN(choice)) {
      console.log("\nExiting...");
      break;
    }

    if (choice < 1 || choice > installableServers.length) {
      console.log("Invalid selection. Try again.\n");
      continue;
    }

    const serverName = installableServers[choice - 1];
    console.log(`\nInstalling ${serverName}...`);

    if (addServer(serverName)) {
      addedCount++;

      // Warning for nia
      if (serverName === "nia") {
        console.log("⚠️  Note: If you just installed nia via pipx, you may need to");
        console.log("   close and reopen your terminal for pipx to be in your PATH\n");
      }
    }
  }

  console.log("\n===================================");
  console.log(`Done! Added ${addedCount} server(s).`);
  console.log("===================================");

  rl.close();
}

main();
