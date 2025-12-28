const { spawn } = require("child_process");

const args = process.argv.slice(2);
const serviceFlags = args.length > 0 ? args : ["-t"];

const child = spawn("npx", ["@humanwhocodes/crosspost", "--mcp", ...serviceFlags], {
  stdio: "inherit",
  env: process.env,
  shell: true,
});

child.on("error", (err) => {
  console.error("Failed to start crosspost:", err);
  process.exit(1);
});

child.on("exit", (code) => {
  process.exit(code || 0);
});
