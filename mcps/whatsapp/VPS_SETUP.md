# WhatsApp MCP — VPS Deployment Guide

Run Beeper Desktop headless on a Linux VPS so the WhatsApp MCP HTTP server is always available, no local Beeper needed.

## Architecture

```
[Claude Code] --HTTP--> [VPS:23380 MCP server] --localhost--> [VPS:23373 Beeper Desktop API]
                                                                       |
                                                       [Xvfb :99 (1920×1080) + openbox WM]
```

Five systemd services keep everything alive:
1. **xvfb** — virtual framebuffer (1920×1080) so Beeper thinks there's a screen
2. **wm** — a minimal window manager (openbox) on the virtual display, so windows are movable/resizable/maximizable over VNC (without it, Beeper's window is unmanaged and you can't drag or resize it)
3. **beeper** — Beeper Desktop running headless under Xvfb
4. **whatsapp-mcp** — FastMCP HTTP server exposing the MCP tools
5. **x11vnc** — VNC server mirroring the virtual display for remote access

## Prerequisites

- Ubuntu 24.04 VPS with SSH access
- RDP access (xrdp) for one-time Beeper authentication
- Ports 23380 (MCP) and 5900 (VNC) open in your cloud provider's firewall (e.g. Azure NSG)
- A VNC viewer on your local machine (e.g. [TigerVNC Viewer](https://sourceforge.net/projects/tigervnc/files/stable/) — download `vncviewer64-*.exe`, standalone, no install)

## Step 1: Install dependencies

```bash
sudo apt update
sudo apt install -y xvfb x11vnc openbox libgtk-3-0 libnotify4 libnss3 libxss1 \
  libasound2t64 libgbm1 git curl
```

## Step 2: Install Beeper Desktop

Download the versioned AppImage, then symlink it to a stable filename (`Beeper.AppImage`). The systemd unit and all docs reference the symlink — when Beeper updates, you only retarget the symlink, no unit edit, no `daemon-reload`. Skipping the symlink leaves the unit hardcoded to a version that will eventually disappear and put `beeper.service` into an infinite `status=203/EXEC` restart loop.

> **Auto-update safety net.** Beeper updates itself in the background by dropping a new `Beeper-<ver>-x86_64.AppImage` into `~/Downloads` and **deleting the old one** — without retargeting your symlink, so it silently goes dangling. The currently-running process keeps going (its files are mounted under `/tmp`), so nothing breaks until the next restart/reboot → `203/EXEC`. To make this impossible, the `beeper.service` in Step 7 has an `ExecStartPre` that repoints `Beeper.AppImage` at the newest versioned AppImage in `~/Downloads` on **every** start. You still create the symlink manually here so the very first launch (Step 3, before the service exists) works.

```bash
cd ~/Downloads
# Find the current version at https://download.beeper.com/linux/appImage/x64 (it 302-redirects to the versioned URL)
wget -O Beeper-4.2.785-x86_64.AppImage "https://download.beeper.com/linux/appImage/x64"
chmod +x Beeper-4.2.785-x86_64.AppImage
ln -sf Beeper-4.2.785-x86_64.AppImage Beeper.AppImage
```

## Step 3: One-time Beeper authentication (requires RDP)

RDP into the VPS and launch Beeper from a terminal:

```bash
./Downloads/Beeper.AppImage --no-sandbox
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

## Step 4: Set timezone

By default most VPS instances use UTC. The MCP server uses the host's local timezone for message timestamps, so set it before running anything:

```bash
sudo timedatectl set-timezone America/Lima
timedatectl   # Should show "Time zone: America/Lima (PET, -0500)"
```

Find your timezone with `timedatectl list-timezones | grep <City>`.

## Step 5: Clone the repo and configure

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

## Step 6: Test manually before creating services

```bash
# Start Xvfb
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 &

# Start a window manager so windows are movable/resizable over VNC
openbox &

# Start Beeper
./Downloads/Beeper.AppImage --no-sandbox &

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

## Step 7: Create systemd services

### Xvfb service

```bash
sudo tee /etc/systemd/system/xvfb.service <<'EOF'
[Unit]
Description=Virtual framebuffer X server

[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
```

### Window manager service (openbox)

Without a window manager, Beeper's window is unmanaged: it opens at a fixed position (often partly off-screen), has no title bar, and **can't be moved, resized, or maximized** over VNC. openbox is a minimal standalone WM with no desktop-environment or D-Bus/Xfconf dependencies (xfwm4, by contrast, crash-loops headless because it needs Xfce's config daemon).

```bash
sudo tee /etc/systemd/system/wm.service <<'EOF'
[Unit]
Description=Window manager (openbox) for display :99
After=xvfb.service
Requires=xvfb.service
Before=beeper.service

[Service]
User=<your-username>
Environment=DISPLAY=:99
ExecStart=/usr/bin/openbox
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
After=xvfb.service wm.service
Requires=xvfb.service
Wants=wm.service

[Service]
User=<your-username>
Environment=DISPLAY=:99
# Self-heal the stable symlink before launch: Beeper auto-updates by dropping a
# new Beeper-<ver>-x86_64.AppImage in ~/Downloads and deleting the old one, which
# leaves Beeper.AppImage dangling -> 203/EXEC on next start. Repoint it at the
# newest versioned AppImage every start so an auto-update can never break boot.
ExecStartPre=/bin/bash -c 'latest=$$(ls -1 /home/<your-username>/Downloads/Beeper-*-x86_64.AppImage 2>/dev/null | sort -V | tail -1); [ -n "$$latest" ] && ln -sf "$$latest" /home/<your-username>/Downloads/Beeper.AppImage; true'
ExecStart=/home/<your-username>/Downloads/Beeper.AppImage --no-sandbox
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

> The `$$` in `ExecStartPre` is intentional: systemd unescapes `$$` to a literal `$` before handing the line to bash, so bash receives `$(...)` and `$latest`. Writing a single `$` would make systemd try to expand `$latest` as an environment variable.

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

### x11vnc service (VNC into the virtual display)

```bash
sudo tee /etc/systemd/system/x11vnc.service <<'EOF'
[Unit]
Description=x11vnc mirror for Xvfb display :99
After=xvfb.service
Requires=xvfb.service

[Service]
ExecStart=/usr/bin/x11vnc -display :99 -nopw -forever -shared
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable xvfb wm beeper whatsapp-mcp x11vnc
sudo systemctl start xvfb wm beeper whatsapp-mcp x11vnc
```

### Verify

```bash
sudo systemctl status xvfb wm beeper whatsapp-mcp x11vnc
curl http://localhost:23373/v1/info    # Beeper API
curl http://localhost:23380/mcp        # MCP server
```

## Step 8: Open ports

The MCP server binds to `0.0.0.0:23380` and x11vnc to `0.0.0.0:5900`, but cloud providers block inbound traffic by default. You need to open both ports.

### Azure

1. Go to your VM in the Azure Portal
2. **Networking → Network settings**
3. Click **Add inbound port rule** and create two rules:

| Field | MCP rule | VNC rule |
|-------|----------|----------|
| Destination port ranges | `23380` | `5900` |
| Protocol | TCP | TCP |
| Action | Allow | Allow |
| Priority | `1010` | `1020` |
| Name | `AllowMCP` | `AllowVNC` |

4. Click **Add** for each. Takes ~30 seconds to propagate.

### AWS

Security Group → Edit inbound rules → Add two rules: Custom TCP port 23380 and Custom TCP port 5900, source 0.0.0.0/0.

### Ubuntu firewall (if enabled)

```bash
sudo ufw allow 23380/tcp
sudo ufw allow 5900/tcp
```

## Step 10: Register in Claude Code

```bash
claude mcp remove whatsapp
claude mcp add -s user --transport http whatsapp http://<your-vps-ip>:23380/mcp
```

## VNC access (interact with headless Beeper)

The x11vnc service mirrors Xvfb display `:99` — the same display Beeper runs on. Connect with any VNC viewer to `<your-vps-ip>:5900` to see and interact with Beeper without stopping any services.

Use this to:
- **Trigger message backfill** — a fresh Beeper install only has recent messages. Open chats in the VNC viewer and scroll up to fetch older history from WhatsApp's servers.
- **Debug Beeper issues** — see exactly what Beeper is showing on the virtual display.
- **Change settings** — toggle Desktop API, manage accounts, etc.

### Recommended VNC viewer

[TigerVNC Viewer](https://sourceforge.net/projects/tigervnc/files/stable/) — download `vncviewer64-<version>.exe` (standalone, no install). Don't download the `-winvnc-` file (that's a server).

### Moving and resizing windows

The `wm` (openbox) service manages windows on `:99`. In the VNC viewer:

- **Drag the title bar** to move a window; **double-click the title bar** to maximize.
- Anywhere in a window: **`Alt` + left-drag = move**, **`Alt` + right-drag = resize** (handy when a window opens larger than the screen or its title bar is off-screen).

If you reconnect after changing the Xvfb resolution, close and reopen the viewer so it picks up the new framebuffer size.

## Message backfill

A freshly installed Beeper instance only has recent messages (~last few hours). Older messages are fetched from WhatsApp's servers when you scroll up in a chat.

To backfill important chats:
1. Connect via VNC to `<your-vps-ip>:5900`
2. Open each chat you care about and scroll up as far as needed
3. Disconnect — messages are now in Beeper's local database and available via the MCP

There is no API to trigger backfill programmatically. Beeper also backfills gradually in the background over time, but scrolling is the fastest way.

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
Xvfb :99 -screen 0 1920x1080x24 &
```

Or use the systemd xvfb service.

### VNC shows a clipped window you can't move/resize

Beeper's window is unmanaged because no window manager is running on `:99`. Confirm with `DISPLAY=:99 xprop -root _NET_SUPPORTING_WM_CHECK` — if it says **`not found`**, there's no live WM. Make sure the `wm` (openbox) service is running:

```bash
sudo systemctl status wm
DISPLAY=:99 xprop -root _NET_SUPPORTING_WM_CHECK   # should print a window id once a WM is up
```

If you see `Xfconf could not be initialized` in `journalctl -u wm`, the unit is pointing at xfwm4 — switch it to openbox (`ExecStart=/usr/bin/openbox`), which has no Xfconf/D-Bus dependency. Also confirm the framebuffer is large enough for Beeper's window (`DISPLAY=:99 xdpyinfo | grep dimensions` → should be `1920x1080`).

### `Archive format is not recognized` (xarchiver popup)

The `.AppImage` file was double-clicked in a file manager. It's not an archive — it's an executable. Run it from the terminal with `chmod +x` and `./Beeper-*.AppImage --no-sandbox`.

### `beeper.service` in restart loop with `status=203/EXEC`

Beeper got updated and the old AppImage filename no longer exists, but the symlink still points at it. **With the Step 7 `beeper.service`, this self-heals** — the `ExecStartPre` retargets the symlink to the newest AppImage on every start, so a simple `sudo systemctl reset-failed beeper && sudo systemctl restart beeper` fixes it (no manual `ln` needed). The steps below are for older units without that `ExecStartPre`, or if Beeper downloaded its update somewhere other than `~/Downloads`.

Check the symlink target:

```bash
ls -la ~/Downloads/Beeper.AppImage
sudo systemctl status beeper --no-pager | head -10
```

If the symlink is broken (or the unit was set up before this guide added the symlink), retarget it to the current AppImage and reset the failure counter:

```bash
cd ~/Downloads
ln -sf Beeper-<new-version>-x86_64.AppImage Beeper.AppImage
sudo systemctl reset-failed beeper
sudo systemctl restart beeper whatsapp-mcp
```

This is also the procedure for routine Beeper version bumps — download the new AppImage, retarget the symlink, restart. No unit edit needed.

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
sudo systemctl status xvfb wm beeper whatsapp-mcp x11vnc

# View logs
journalctl -u whatsapp-mcp --no-pager -n 50
journalctl -u beeper --no-pager -n 50

# Restart everything
sudo systemctl restart xvfb wm beeper whatsapp-mcp x11vnc

# Stop everything
sudo systemctl stop whatsapp-mcp x11vnc beeper wm xvfb

# Update the MCP code
cd ~/github-repositories/better-mcp && git pull && cd mcps/whatsapp && uv sync
sudo systemctl restart whatsapp-mcp
```
