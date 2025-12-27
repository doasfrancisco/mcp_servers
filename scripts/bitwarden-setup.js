#!/usr/bin/env node

const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

const isWindows = process.platform === "win32";

const POWERSHELL_FUNCTIONS = `
# Bitwarden
function bitwarden {
    param([string]$cmd, [string]$action, [string]$name)

    if (-not $cmd) {
        $env:BW_SESSION = (bw unlock --raw)
        return
    }

    if ($cmd -eq "env" -and $action -eq "pull" -and $name) {
        bw get item $name | jq -r '.notes' > .env
        Write-Host "Pulled .env from $name"
        return
    }

    if ($cmd -eq "env" -and $action -eq "push" -and $name) {
        $notes = Get-Content .env -Raw
        bw get item $name | jq --arg notes "$notes" '.notes = $notes' | bw edit item $name | Out-Null
        Write-Host "Pushed .env to $name"
        return
    }
}
`;

const BASH_FUNCTIONS = `
# Bitwarden
bitwarden() {
    if [ -z "$1" ]; then
        export BW_SESSION=$(bw unlock --raw)
        return
    fi

    if [ "$1" = "env" ] && [ "$2" = "pull" ] && [ -n "$3" ]; then
        bw get item "$3" | jq -r '.notes' > .env
        echo "Pulled .env from $3"
        return
    fi

    if [ "$1" = "env" ] && [ "$2" = "push" ] && [ -n "$3" ]; then
        bw get item "$3" | jq --arg notes "$(cat .env)" '.notes = $notes' | bw edit item "$3" > /dev/null
        echo "Pushed .env to $3"
        return
    fi

    echo "Usage: bitwarden [env pull|push <name>]"
}
`;

function getProfilePath() {
    if (isWindows) {
        try {
            const profilePath = execSync('pwsh -Command "echo $PROFILE"', { encoding: "utf-8" }).trim();
            return profilePath;
        } catch {
            throw new Error("PowerShell profile not found!");
        }
    } else {
        return path.join(os.homedir(), ".bashrc");
    }
}

function setup() {
    const profilePath = getProfilePath();
    const functions = isWindows ? POWERSHELL_FUNCTIONS : BASH_FUNCTIONS;
    const marker = "bitwarden";

    console.log(`Setting up bitwarden helpers...`);
    console.log(`Profile: ${profilePath}`);

    const profileDir = path.dirname(profilePath);
    if (!fs.existsSync(profileDir)) {
        throw new Error(`Terminal profile ${profileDir} does not exist!`);
    }

    let content = "";
    if (fs.existsSync(profilePath)) {
        content = fs.readFileSync(profilePath, "utf-8");
    }
    if (content.includes(marker)) {
        console.log("\nBitwarden helpers already installed!");
        console.log("To reinstall, remove the existing block from your profile first.");
        return;
    }

    // Append functions
    fs.appendFileSync(profilePath, "\n" + functions);

    console.log("\nInstalled successfully!");
    console.log("\nRestart your terminal or run:");
    if (isWindows) {
        console.log("  . $PROFILE");
    } else {
        console.log("  source ~/.bashrc");
    }

    console.log("\nUsage:");
    console.log("  bitwarden              # Unlock vault");
    console.log("  bitwarden env pull x   # Pull .env from item 'x'");
    console.log("  bitwarden env push x   # Push .env to item 'x'");
}

setup();
