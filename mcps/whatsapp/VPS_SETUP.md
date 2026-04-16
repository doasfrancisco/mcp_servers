# WhatsApp MCP — VPS Deployment Guide

Run Beeper Desktop headless on a Linux VPS so the WhatsApp MCP HTTP server is always available, no local Beeper needed.

## Architecture

```
[Claude Code] --HTTP--> [VPS:23380 MCP server] --localhost--> [VPS:23373 Beeper Desktop API]
                                                                       |
                                                              [Xvfb virtual display :99]
```

Three systemd services keep everything alive:
1. **xvfb** — virtual framebuffer so Beeper thinks there's a screen
2. **beeper** — Beeper Desktop running headless under Xvfb
3. **whatsapp-mcp** — FastMCP HTTP server exposing the MCP tools

## Prerequisites

- Ubuntu 24.04 VPS with SSH access
- RDP access (xrdp) for one-time Beeper authentication
- Port 23380 open in your cloud provider's firewall (e.g. Azure NSG)

## Step 1: Install dependencies

```bash
sudo apt update
sudo apt install -y xvfb libgtk-3-0 libnotify4 libnss3 libxss1 \
  libasound2t64 libgbm1 git curl
```

## Step 2: Install Beeper Desktop

```bash
cd ~/Downloads
wget -O Beeper-4.2.742-x86_64.AppImage "https://download.beeper.com/linux/appImage/x64"
chmod +x Beeper-4.2.742-x86_64.AppImage
```

## Step 3: One-time Beeper authentication (requires RDP)

RDP into the VPS and launch Beeper from a terminal:

```bash
./Downloads/Beeper-4.2.742-x86_64.AppImage --no-sandbox
```

In Beeper:
1. Log in to your Beeper account
2. Connect WhatsApp (scan QR with your phone)
3. Wait for "Setting up encryption..." and chat sync to complete
4. **Settings → Developers → toggle "Beeper Desktop API" ON**
5. **Settings → Developers → toggle "Start on launch" ON**
6. **Settings → Developers → toggle "Built-in MCP Server" OFF** (we use our own MCP)
7. **Settings → Developers → Approved connections → "+" → copy the access token**

Verify the API is running:

```bash
curl http://localhost:23373/v1/info
```

Close Beeper (Ctrl+C) and close RDP. You won't need RDP again.

## Step 4: Clone the repo and configure

```bash
cd ~
git clone <your-repo-url> github-repositories/better-mcp
cd github-repositories/better-mcp/mcps/whatsapp
```

Create the `.env` file:

```bash
echo "BEEPER_ACCESS_TOKEN='<paste-your-token>'" > .env
```

Install uv and sync dependencies:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
uv sync
```

Copy `tags.json` from your local machine if you have existing tags (optional).

## Step 5: Test manually before creating services

```bash
# Start Xvfb
export DISPLAY=:99
Xvfb :99 -screen 0 1280x720x24 &

# Start Beeper
./Downloads/Beeper-4.2.742-x86_64.AppImage --no-sandbox &

# Wait for Beeper to initialize
sleep 15

# Verify Beeper API
curl http://localhost:23373/v1/info

# Start MCP
cd ~/github-repositories/better-mcp/mcps/whatsapp
uv run fastmcp run server.py --transport http --host 0.0.0.0 --port 23380
```

From your local machine:

```bash
curl http://<your-vps-ip>:23380/mcp
# Should return a JSON-RPC response (error about text/event-stream is normal — it means the server is alive)
```

Kill everything before proceeding (`pkill -f Xvfb && pkill -f beepertexts && pkill -f fastmcp`).

## Step 6: Create systemd services

### Xvfb service

```bash
sudo tee /etc/systemd/system/xvfb.service <<'EOF'
[Unit]
Description=Virtual framebuffer X server

[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1280x720x24
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
```

### Beeper service

```bash
sudo tee /etc/systemd/system/beeper.service <<'EOF'
[Unit]
Description=Beeper Desktop (headless)
After=xvfb.service
Requires=xvfb.service

[Service]
User=<your-username>
Environment=DISPLAY=:99
ExecStart=/home/<your-username>/Downloads/Beeper-4.2.742-x86_64.AppImage --no-sandbox
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### WhatsApp MCP service

```bash
sudo tee /etc/systemd/system/whatsapp-mcp.service <<'EOF'
[Unit]
Description=WhatsApp MCP HTTP server
After=beeper.service
Requires=beeper.service

[Service]
User=<your-username>
WorkingDirectory=/home/<your-username>/github-repositories/better-mcp/mcps/whatsapp
ExecStart=/home/<your-username>/.local/bin/uv run fastmcp run server.py --transport http --host 0.0.0.0 --port 23380
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable xvfb beeper whatsapp-mcp
sudo systemctl start xvfb beeper whatsapp-mcp
```

### Verify

```bash
sudo systemctl status xvfb beeper whatsapp-mcp
curl http://localhost:23373/v1/info    # Beeper API
curl http://localhost:23380/mcp        # MCP server
```

## Step 7: Open the port

The MCP server binds to `0.0.0.0:23380` but cloud providers block inbound traffic by default. You need to open the port in both the cloud firewall and (optionally) the OS firewall.

### Azure

1. Go to your VM in the Azure Portal
2. **Networking → Network settings**
3. Click **Add inbound port rule** (or find the existing NSG rules)
4. Fill in:
   - **Destination port ranges**: `23380`
   - **Protocol**: TCP
   - **Action**: Allow
   - **Priority**: `1010` (any unused number)
   - **Name**: `AllowMCP`
5. Click **Add**. Takes ~30 seconds to propagate.

### AWS

Security Group → Edit inbound rules → Add rule → Custom TCP, port 23380, source 0.0.0.0/0.

### Ubuntu firewall (if enabled)

```bash
sudo ufw allow 23380/tcp
```

## Step 8: Register in Claude Code

```bash
claude mcp remove whatsapp
claude mcp add -s user --transport http whatsapp http://<your-vps-ip>:23380/mcp
```

## Common errors

### `The SUID sandbox helper binary was found, but is not configured correctly`

Beeper's Electron sandbox doesn't work on most VPS environments. Always launch with `--no-sandbox`:

```bash
./Beeper-4.2.742-x86_64.AppImage --no-sandbox
```

### `Missing X server or $DISPLAY`

Beeper needs a display. If running from SSH without Xvfb:

```bash
export DISPLAY=:99
Xvfb :99 -screen 0 1280x720x24 &
```

Or use the systemd xvfb service.

### `Archive format is not recognized` (xarchiver popup)

The `.AppImage` file was double-clicked in a file manager. It's not an archive — it's an executable. Run it from the terminal with `chmod +x` and `./Beeper-*.AppImage --no-sandbox`.

### `APIConnectionError: Connection error` in MCP logs

The MCP server can't reach Beeper's Desktop API on `localhost:23373`. Causes:

1. **Beeper Desktop API not enabled** — RDP in, open Beeper, toggle it on in Settings → Developers. The setting persists after restart.
2. **Beeper not fully started** — wait 10-15 seconds after starting the beeper service, then check `curl http://localhost:23373/v1/info`.
3. **Beeper crashed** — check `journalctl -u beeper --no-pager -n 30`.

### `curl: Failed to connect to <ip> port 23380`

The port isn't open. Check:

1. Cloud provider firewall (Azure NSG, AWS Security Group)
2. Ubuntu firewall: `sudo ufw status` — if active, run `sudo ufw allow 23380/tcp`
3. MCP service running: `sudo systemctl status whatsapp-mcp`

### Desktop API setting doesn't persist after systemd restart

This happens if the systemd Beeper instance uses a different config than the RDP session. Fix:

1. `sudo systemctl stop beeper whatsapp-mcp`
2. RDP in, launch Beeper manually, enable Desktop API, close Beeper
3. `sudo systemctl start beeper whatsapp-mcp`
4. Verify: `curl http://localhost:23373/v1/info`

### JSON-RPC error when curling the MCP

```json
{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Not Acceptable: Client must accept text/event-stream"}}
```

This is **normal**. The MCP server is alive — curl just isn't a valid MCP client. Only Claude Code (or other MCP clients) can speak the full protocol.

## Maintenance

```bash
# Check status
sudo systemctl status xvfb beeper whatsapp-mcp

# View logs
journalctl -u whatsapp-mcp --no-pager -n 50
journalctl -u beeper --no-pager -n 50

# Restart everything
sudo systemctl restart xvfb beeper whatsapp-mcp

# Stop everything
sudo systemctl stop whatsapp-mcp beeper xvfb

# Update the MCP code
cd ~/github-repositories/better-mcp && git pull && cd mcps/whatsapp && uv sync
sudo systemctl restart whatsapp-mcp
```
