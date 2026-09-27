---
name: windows-hosting-setup
description: Set up Docker + cloudflared on the Windows store laptop, run the PickerWheel docker-compose stack there, and connect the existing pickerwheel.mytmobiles.com Cloudflare Tunnel from that machine. Use when moving PickerWheel hosting from a dev Mac onto the actual Windows store PC, or reconnecting the tunnel after a reboot/network change.
---

# PickerWheel Windows Hosting Setup

## What this is

PickerWheel currently runs via `docker-compose.yml` on a developer's Mac for
testing, tunneled to the public internet at `pickerwheel.mytmobiles.com`
through a named Cloudflare Tunnel (`pickerwheel-admin`, tunnel id
`cb7a20ad-a009-4875-8850-79000bd32542`). The end target is a Windows laptop
at the actual store, permanently.

**Cloudflare-side setup (DNS, the Access Application, the 5-email allow
policy, One-Time-PIN identity provider, login branding) is already done in
the Cloudflare account and does not need to be repeated.** This skill is
about getting a `cloudflared` connector and the Docker stack running
*on the Windows machine* and pointed at that same existing tunnel - not
about recreating Cloudflare Access from scratch.

## Known constraints from the original setup (carry these over)

- **`--workers` must stay at 1** in the gunicorn command (`docker-compose.yml`).
  Socket.IO has no message queue configured, so a second worker/replica would
  silently drop real-time updates for some connected clients. Threads (not
  workers) were raised to 16 for headroom - don't lower that without reason.
- **`ALLOWED_ORIGINS`** in `docker-compose.yml` must include
  `https://pickerwheel.mytmobiles.com`, or Socket.IO rejects every real
  browser WebSocket handshake with "not an accepted origin" (surfaces as
  intermittent 400/502s, not an obvious error).
- **`ADMIN_PASSWORD`** in `docker-compose.yml` is still the shipped default
  (`myTAdmin2025`) as of this writing - it was deliberately left alone until
  testing finished. Rotate it before this becomes the real production
  deployment, and update it in both `docker-compose.yml` and anywhere else
  that references it.
- The routes `/app` (wheel), `/admin` (admin panel), and `/` redirecting to
  `/admin` *only* when the request carries a `CF-Connecting-IP` header (i.e.
  came through Cloudflare, not local/LAN) are already implemented in
  `backend/app/__init__.py`. Pull the latest `main` to get this.
- Admin login uses a session cookie, not a per-request password (see
  `backend/app/routes/admin.py`), and auto-fills the audit-log actor from
  `Cf-Access-Authenticated-User-Email` when accessed via the public domain.

## Why the local IP doesn't matter for the tunnel

`cloudflared`'s ingress config points at `http://localhost:9080` - loopback,
not the machine's LAN IP. Since `cloudflared` runs on the *same* machine as
the Docker stack, this stays correct no matter what WiFi network the laptop
joins or what IP it's assigned. **The tunnel needs no reconfiguration when
the network changes.**

The one thing that *does* depend on the local network is customers reaching
the wheel directly over LAN (e.g. `http://192.168.1.34:9080` from a phone on
the store WiFi, bypassing the tunnel entirely for lower latency - the public
domain is comparatively slow and meant for admin/remote access, not the
customer-facing flow). That LAN IP changes on every new network. See the
"Find the current LAN URL" section below for a one-liner to reprint it
whenever the network changes, rather than hardcoding it anywhere.

## Steps

### 1. Prerequisites on the Windows laptop

- Install **Docker Desktop for Windows** (WSL2 backend) -
  https://www.docker.com/products/docker-desktop/ - and make sure it's
  actually running (check the system tray icon) before step 4.
- Install **Git for Windows** if not already present.
- Install **cloudflared**:
  ```powershell
  winget install --id Cloudflare.cloudflared
  ```
  Verify: `cloudflared --version`

### 2. Get the code

```powershell
git clone https://github.com/storetmobiles2-code/pickerwheel-v1-docker-version.git
cd pickerwheel-v1-docker-version
git checkout main
git pull
```

(If working from a fork remote instead, adjust the URL - see the repo's
existing git remotes for the pattern: `origin` read-only, changes go via a
fork + PR.)

### 3. Get the tunnel running on this machine

The tunnel's actual credentials (a private key file) must **never** be
committed to git or pasted into a chat/skill file - treat it like a
password. Two ways to get `cloudflared` authorized on this new machine:

**Option A - reuse the existing tunnel (preferred, keeps the same domain
working with zero Cloudflare-side changes):**

1. On whichever machine currently holds it, securely copy these two files
   to the Windows machine's `%USERPROFILE%\.cloudflared\` folder (AirDrop,
   an encrypted USB stick, or a password manager's secure file storage -
   not email, not Slack, not committed anywhere):
   - `cb7a20ad-a009-4875-8850-79000bd32542.json` (the tunnel credentials)
   - `cert.pem` (the account-level origin certificate)
2. Create `%USERPROFILE%\.cloudflared\config.yml`:
   ```yaml
   tunnel: cb7a20ad-a009-4875-8850-79000bd32542
   credentials-file: C:\Users\<you>\.cloudflared\cb7a20ad-a009-4875-8850-79000bd32542.json

   ingress:
     - hostname: pickerwheel.mytmobiles.com
       service: http://localhost:9080
     - service: http_status:404
   ```
3. Stop `cloudflared` wherever it's currently running (e.g. on the dev Mac:
   `kill <pid>` after finding it with `ps aux | grep cloudflared`) - only
   one connector should serve customer traffic at a time to avoid confusion
   about which machine is actually live, though Cloudflare does support
   multiple simultaneous connectors per tunnel if you deliberately want
   redundancy later.

**Option B - start fresh (if the credentials file was lost, or this is a
clean rebuild):**

```powershell
cloudflared tunnel login
# Browser opens -> select the mytmobiles.com zone -> Authorize
cloudflared tunnel create pickerwheel-admin
cloudflared tunnel route dns pickerwheel-admin pickerwheel.mytmobiles.com
```
Then write `config.yml` as in Option A, but with the **new** tunnel ID
`cloudflared tunnel create` just printed (it will differ from the one
above). Note the old tunnel's DNS record will need deleting in the
Cloudflare dashboard first if one still points at a dead tunnel.

### 4. Install cloudflared as a Windows service (survives reboot/network changes/sleep)

```powershell
cloudflared service install
```
This reads the `config.yml` from step 3 and registers `cloudflared` as a
Windows service that starts automatically on boot and reconnects on its own
after any network interruption - no manual restart needed when the WiFi
changes, sleeps, or the laptop reboots. Confirm it's running:
```powershell
Get-Service cloudflared
```

### 5. Start the app

```powershell
docker compose up -d
```
Wait for `pickerwheel-db` to report healthy, then confirm:
```powershell
curl http://localhost:9080/
```
Should return the wheel page HTML. If Docker Desktop was just installed,
the first `docker compose up -d` will take longer while it builds the image.

### 6. Verify end-to-end

```powershell
curl http://localhost:9080/                          # local wheel - HTTP 200
curl http://localhost:9080/admin                      # local admin - HTTP 200
curl -I https://pickerwheel.mytmobiles.com/           # public - 302 to Cloudflare Access login
```
Then in a browser: visit `https://pickerwheel.mytmobiles.com/`, complete the
email one-time-PIN login (one of the 5 allow-listed addresses), and confirm
it lands on `/admin` automatically.

### 7. Find the current LAN URL (whenever the network changes)

Run this any time the laptop joins a different WiFi network, to get the
current URL for customers on that same local network:

```powershell
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notmatch '^169\.254'
} | Select-Object -First 1).IPAddress
Write-Host "Customer wheel (this network): http://$($ip):9080"
```

Nothing needs reconfiguring for this - it's just a fresh URL to hand out
(write on a sign, put in a QR code, etc.) since the docker-compose stack
already listens on `0.0.0.0:9080`, reachable at whatever the current IP is.
The Cloudflare Tunnel (admin access, `pickerwheel.mytmobiles.com`) is
entirely unaffected by this and needs no changes when the network changes.

## Troubleshooting

- **Public domain returns Cloudflare error 530 / doesn't load**: the
  `cloudflared` service likely isn't running or hasn't reconnected yet.
  Check `Get-Service cloudflared` and its logs (Windows Event Viewer, or run
  `cloudflared tunnel run pickerwheel-admin` manually in a terminal to see
  live output).
- **Browser console shows repeated WebSocket handshake failures /
  intermittent 400 or 502 through the public domain**: check
  `ALLOWED_ORIGINS` in `docker-compose.yml` includes
  `https://pickerwheel.mytmobiles.com` exactly, then
  `docker compose up -d pickerwheel` to recreate the container with the
  updated env var.
- **Spin button gets stuck on "SPINNING..." forever**: check gunicorn is
  actually running the app (`docker top pickerwheel-app` should show
  `gunicorn --worker-class gthread --workers 1 --threads 16 ...`, not
  `python main.py`) - the dev server can't handle real concurrent
  WebSocket+HTTP traffic and requests can hang indefinitely. The frontend
  also has a 15s client-side timeout on the spin flow as a backstop
  (`fetchWithTimeout` in `frontend/wheel.js`).
- **Login page shows "restricted to members of the account" instead of an
  email field**: someone clicked "Sign in with Cloudflare" instead of using
  the email one-time-PIN field - that's a different, unrelated Cloudflare
  login path tied to actual Cloudflare.com account membership. The Access
  Application is already scoped to only offer the one-time-PIN provider
  (`allowed_idps` on the PickerWheel Access Application), so this shouldn't
  normally appear.
