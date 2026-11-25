<div align="center">

# `vanish`

**A zero-persistence, self-destructing local chat and file-sharing room for LAN & Wi-Fi networks.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![WebSockets](https://img.shields.io/badge/Transport-WebSockets-orange?style=flat-square)]()
[![Persistence](https://img.shields.io/badge/Persistence-Zero%20%28RAM%20%2B%20Temp%20Dir%29-red?style=flat-square)]()
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)]()

*Spin up an ephemeral web room on your machine in seconds. Devices on the same Wi-Fi scan a QR code, chat, and drop files—and when the clock hits zero, every message, file, and process trace vanishes.*

</div>

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [How It Works (Architecture & Lifecycle)](#how-it-works-architecture--lifecycle)
- [Installation & Setup](#installation--setup)
  - [Prerequisites](#prerequisites)
  - [Standard Setup](#standard-setup)
  - [Virtual Environment Setup (Recommended)](#virtual-environment-setup-recommended)
- [Usage & CLI Reference](#usage--cli-reference)
  - [Quick Start](#quick-start)
  - [Command-Line Flags](#command-line-flags)
  - [Example Scenarios](#example-scenarios)
- [Host vs. Guest Roles](#host-vs-guest-roles)
- [Project Structure](#project-structure)
- [API & WebSocket Protocol](#api--websocket-protocol)
  - [HTTP Endpoints](#http-endpoints)
  - [WebSocket Events](#websocket-events)
- [Security Model, Hardening & Limitations](#security-model-hardening--limitations)
  - [Built-In Safeguards](#built-in-safeguards)
  - [Threat Model & Current Boundaries](#threat-model--current-boundaries)
- [Troubleshooting & Firewall Tips](#troubleshooting--firewall-tips)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Sharing links, snippets, or files across laptops and phones on the same Wi-Fi usually forces you to log into cloud drives, message yourself on third-party chat apps, or configure local SMB/AirDrop permissions. Afterward, those files sit forgotten on external servers or shared folders.

**`vanish`** solves this by turning any Windows, macOS, or Linux machine into an **ephemeral, single-session web server**:

1. **No client installs:** Guests join directly from any mobile or desktop browser.
2. **No accounts or databases:** Chat history lives strictly in process memory (`RAM`).
3. **Automatic self-destruction:** When the countdown expires—or when the host triggers **End Now**—the server notifies clients, closes sockets, wipes memory, recursively deletes its temporary upload directory, and terminates its own OS process.

---

## Key Features

- **Instant LAN Discovery & QR Onboarding:** Automatically detects your machine's local IPv4 address, prints an ASCII QR code directly in the terminal, and serves a crisp PNG QR code inside the web sidebar.
- **Cryptographic Capability Tokens:** Generates separate URL-safe tokens (`secrets.token_urlsafe`) for **Guests** (`join_token`) and the **Host** (`host_token`).
- **Real-Time WebSocket Messaging:** Low-latency group chat with live user presence lists, join/leave system events, typing indicators, and server-synced countdown timers.
- **Drag-and-Drop & Button File Sharing:** Streamed chunked uploads with live download cards broadcast to everyone in the room.
- **Strict Resource & Storage Quotas:** Configurable caps on simultaneous connected devices (`--max-devices`), individual file sizes (`--max-file-mb`), and total session disk usage (`--max-total-mb`).
- **Deterministic Cleanup Guarantee:** Cleanup hooks run across timer expiration, manual host termination, FastAPI lifespan shutdown, and `Ctrl+C` (`SIGINT`) interrupts.

---

## How It Works (Architecture & Lifecycle)

```text
+-------------------+       1. Scan QR / Open Join URL       +--------------------+
|   Guest Browser   | -------------------------------------> |                    |
| (Phone / Laptop)  | <------------------------------------- |   vanish Server    |
+-------------------+       2. HTML/JS + WebSocket (/ws)     |   (FastAPI +       |
                                                             |    Uvicorn)        |
+-------------------+       3. Host URL + End Now Control    |                    |
|   Host Browser    | <====================================> |  - RAM Message Log |
+-------------------+                                        |  - /tmp/vanish_*   |
                                                             +--------------------+
                                                                       |
                                              4. Timer == 0 / End Now / Ctrl+C
                                                                       v
                                                             [ Wipe RAM + Delete ]
                                                             [ Temp Dir + Exit   ]
```

### Shutdown Sequence

When the session ends, `vanish` executes a strict 5-step teardown:

1. **Broadcast:** Pushes a `{"type": "session_ended"}` event over all active WebSockets so connected browsers immediately display the expired screen.
2. **Disconnect:** Gracefully closes all open WebSocket connections (`code=1000`).
3. **Memory Wipe:** Clears the in-memory message buffer, file registry, and active connection maps.
4. **Disk Purge:** Recursively removes the session's `tempfile.mkdtemp(prefix="vanish_")` folder via `shutil.rmtree(..., ignore_errors=True)`.
5. **Process Exit:** Terminates the Python/Uvicorn process cleanly so the port is freed immediately.

---

## Installation & Setup

### Prerequisites

- **Python 3.10+** installed on the host machine
- All participating devices connected to the **same local network (Wi-Fi / LAN)**

### Standard Setup

```bash
git clone https://github.com/Hesamtkh-dev/vanish.git
cd vanish
pip install -r requirements.txt
```

### Virtual Environment Setup (Recommended)

<details>
<summary><strong>Linux / macOS</strong></summary>

```bash
git clone https://github.com/Hesamtkh-dev/vanish.git
cd vanish
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
git clone https://github.com/Hesamtkh-dev/vanish.git
cd vanish
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
</details>

---

## Usage & CLI Reference

### Quick Start

Start a 15-minute room allowing up to 10 connected devices:

```bash
python main.py --minutes 15 --max-devices 10
```

You will see output similar to:

```text
=== VANISH ROOM READY ===
Join link (share on WiFi): http://192.168.1.42:8000/?token=a8F9kL2mQp7xR1vZ
Host link (KEEP PRIVATE):   http://192.168.1.42:8000/?token=9xT4wN8cV2bM6qL0pK3zY1wE
Lifetime: 15m | Max devices: 10 | Max file: 25MB | Max total: 300MB

[ ASCII QR CODE PRINTED HERE ]
```

### Command-Line Flags

| Flag | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `--minutes` | `int` | `10` | Total room lifetime in minutes before automatic self-destruction. |
| `--max-devices` | `int` | `10` | Maximum number of simultaneous WebSocket client connections. |
| `--port` | `int` | `8000` | Local TCP port the HTTP/WebSocket server binds to (`0.0.0.0`). |
| `--max-file-mb` | `int` | `25` | Maximum allowed size (in megabytes) for any single uploaded file. |
| `--max-total-mb` | `int` | `300` | Cumulative storage cap (in megabytes) across all files in the session. |

### Example Scenarios

- **Quick 5-minute file drop between phone and laptop:**
  ```bash
  python main.py --minutes 5 --max-devices 2 --max-file-mb 100 --max-total-mb 200
  ```
- **Classroom or workshop whiteboard session (30 minutes, 25 participants, text-focused):**
  ```bash
  python main.py --minutes 30 --max-devices 25 --max-file-mb 10 --max-total-mb 250
  ```
- **Running on an alternate port when `8000` is busy:**
  ```bash
  python main.py --port 8080
  ```

---

## Host vs. Guest Roles

`vanish` separates room moderation from normal participation using two distinct capability URLs generated at startup:

| Capability | Guest (`join_token`) | Host (`host_token`) |
| :--- | :---: | :---: |
| Read & send chat messages | Yes | Yes |
| Upload & download files | Yes | Yes |
| View connected users & timer | Yes | Yes |
| Copy guest join link / view QR | Yes | Yes |
| **Trigger immediate room wipe (`End Now`)** | **No** | **Yes** |

> **Important:** Do not share your **Host link** with guests. Anyone holding the `host_token` URL can terminate the room early.

---

## Project Structure

```text
vanish/
├── main.py                  # FastAPI server, CLI parser, room state, WebSocket hub & cleanup lifecycle
├── requirements.txt         # Python dependencies (fastapi, uvicorn, qrcode, python-multipart)
├── templates/
│   ├── index.html           # Main ephemeral chat room & join modal UI
│   └── expired.html         # Post-destruction / unauthorized landing page
├── static/
│   ├── app.js               # WebSocket client, countdown sync, drag-and-drop uploader & DOM renderer
│   └── style.css            # Responsive dark-mode UI styling
└── README.md                # Documentation
```

---

## API & WebSocket Protocol

### HTTP Endpoints

| Method | Endpoint | Auth Query | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | `?token=...` | Serves the chat interface (`index.html`) or `expired.html` (`403`/`410`). |
| `GET` | `/api/meta` | `?token=...` | Returns room role, remaining seconds, storage usage, active users, and recent messages. |
| `GET` | `/api/qr` | `?token=...` | Dynamically generates and streams a PNG QR code pointing to the guest join URL. |
| `POST` | `/api/upload` | `?token=...` | Accepts `multipart/form-data` uploads, enforces size quotas, and broadcasts file metadata. |
| `GET` | `/api/files/{file_id}` | `?token=...` | Streams a previously uploaded file as `application/octet-stream`. |
| `POST` | `/api/end` | `?token=<host>` | **Host-only.** Immediately triggers room teardown and process shutdown. |

### WebSocket Events

Connect to `ws://<host>:<port>/ws?token=<token>&name=<display_name>`.

- **Client $\rightarrow$ Server:**
  - `{"type": "chat", "text": "Hello room"}` — Broadcast a chat message (max 2,000 chars).
  - `{"type": "typing"}` — Notify peers that the user is currently typing.
  - `{"type": "ping"}` — Heartbeat requesting authoritative `seconds_left` from the server.
- **Server $\rightarrow$ Client:**
  - `{"type": "message", "message": {...}}` — New text message or file attachment card.
  - `{"type": "presence", "users": [...], "event": "...", "seconds_left": 540}` — User join/leave updates.
  - `{"type": "typing", "user": "Alice"}` — Ephemeral typing notification.
  - `{"type": "pong", "seconds_left": 539}` — Clock synchronization response.
  - `{"type": "session_ended", "reason": "..."}` — Signals imminent room destruction.

---

## Security Model, Hardening & Limitations

### Built-In Safeguards

- **Path Traversal Protection:** Uploaded filenames are stripped with `os.path.basename()`, sanitized via strict allowlist regexes, prefixed with random UUIDs, and verified with `Path.is_relative_to()` before serving downloads.
- **XSS Mitigation:** All user-supplied names, messages, and filenames are rendered on the client using `textContent` rather than `innerHTML`.
- **Streamed Quota Enforcement:** Uploads are read in 64 KB chunks and aborted mid-stream (`HTTP 413`) with partial file deletion the moment either `--max-file-mb` or `--max-total-mb` is exceeded.
- **Basic Anti-Spam Throttling:** Per-IP sliding-window rate limiting prevents rapid WebSocket message flooding.
- **Zero Disk Footprint for Text:** Messages are never written to SQLite, logs, or temporary files—only uploaded binary payloads touch the OS temp directory until cleanup.

### Threat Model & Current Boundaries

`vanish` is engineered for **trusted local networks** (home Wi-Fi, study groups, hackathons, or office desks). Keep the following limitations in mind:

- **Plaintext HTTP / WS on LAN:** Traffic is unencrypted (`http://` and `ws://`). A passive sniffer on the same untrusted public Wi-Fi could observe messages or tokens in transit. Do not use `vanish` over untrusted public hotspots for sensitive secrets without wrapping it in TLS or an encrypted tunnel.
- **Local Network Scope Only:** The server binds to your LAN interface (`0.0.0.0`). Devices outside your router/NAT cannot connect unless you explicitly expose the port via a reverse tunnel (e.g., Cloudflare Tunnel, ngrok, or WireGuard).
- **OS Swap / Disk Forensics:** While `vanish` deletes its temporary directory cleanly upon exit, standard filesystem deletion (`unlink`) does not perform multi-pass secure shredding on SSDs/flash storage.

---

## Troubleshooting & Firewall Tips

- **Guests can't load the join link on their phone:**
  - Verify both devices are on the **exact same Wi-Fi network** (and not separated by a Guest Wi-Fi isolation / AP isolation setting).
  - Check your host OS firewall:
    - **Windows:** Allow Python / Uvicorn through Windows Defender Firewall for **Private** networks when prompted.
    - **macOS:** Ensure Python is allowed under *System Settings $\rightarrow$ Network $\rightarrow$ Firewall*.
    - **Linux (`ufw`):** Temporarily allow the port with `sudo ufw allow 8000/tcp`.
- **Wrong IP address detected:**
  - If you have active VPNs, Docker bridges, or virtual adapters, `vanish` may pick a virtual interface IP. Check `ipconfig` (Windows) or `ip a` / `ifconfig` (Linux/macOS) and substitute your Wi-Fi adapter's `192.168.x.x` or `10.x.x.x` address into the URL.

---

## Roadmap

- [ ] Optional 4–6 digit room PIN in addition to the URL token
- [ ] Single-download ("burn after reading") toggle for sensitive file drops
- [ ] Optional `--tunnel` flag to spin up a temporary encrypted public URL
- [ ] Ephemeral image preview thumbnails & syntax-highlighted code snippets
- [ ] Standalone single-file binaries (`PyInstaller`) for Windows, macOS, and Linux

---

## Contributing

Contributions, bug reports, and security hardening suggestions are welcome!

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/burn-after-reading`)
3. Commit your changes (`git commit -m "Add single-download file option"`)
4. Push to your branch (`git push origin feat/burn-after-reading`)
5. Open a Pull Request

---

## License

Distributed under the **MIT License**. See `LICENSE` for more information.