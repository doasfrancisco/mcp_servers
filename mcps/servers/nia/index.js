const { spawn } = require("child_process");

const IS_WINDOWS = process.platform === "win32";

// Build the command based on platform
const command = IS_WINDOWS ? "cmd" : "pipx";
const args = IS_WINDOWS
  ? ["/c", "pipx", "run", "nia-mcp-server"]
  : ["run", "nia-mcp-server"];

// Spawn the process and pipe stdio
const child = spawn(command, args, {
  stdio: "inherit",
  env: process.env,
});

child.on("error", (err) => {
  console.error("Failed to start nia-mcp-server:", err.message);
  process.exit(1);
});

child.on("exit", (code) => {
  process.exit(code || 0);
});
