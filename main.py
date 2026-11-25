import argparse
import asyncio
import io
import os
import re
import secrets
import shutil
import socket
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import qrcode
import uvicorn
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent


@dataclass
class Config:
    minutes: int = 10
    max_devices: int = 10
    port: int = 8000
    max_file_mb: int = 25
    max_total_mb: int = 300


@dataclass
class ChatMessage:
    id: str
    sender: str
    role: str  # "guest" | "host" | "system"
    text: Optional[str] = None
    file: Optional[dict] = None
    timestamp: float = field(default_factory=time.time)


class RoomState:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.join_token = secrets.token_urlsafe(12)
        self.host_token = secrets.token_urlsafe(18)
        self.created_at = time.time()
        self.expires_at = self.created_at + (cfg.minutes * 60)
        self.ended = False
        self.cleanup_done = False

        self.upload_dir = Path(tempfile.mkdtemp(prefix="vanish_"))
        self.total_uploaded_bytes = 0
        self.files: Dict[str, dict] = {}
        self.messages: List[ChatMessage] = []
        self.connections: Dict[str, WebSocket] = {}
        self.conn_names: Dict[str, str] = {}
        self.conn_roles: Dict[str, str] = {}
        self.ip_msg_timestamps: Dict[str, List[float]] = {}
        self.lock = asyncio.Lock()

    @property
    def seconds_left(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    def cleanup_disk_and_memory(self) -> None:
        if self.cleanup_done:
            return
        self.cleanup_done = True
        self.messages.clear()
        self.files.clear()
        self.connections.clear()
        self.conn_names.clear()
        self.conn_roles.clear()
        try:
            if self.upload_dir.exists():
                shutil.rmtree(self.upload_dir, ignore_errors=True)
        except Exception:
            pass

    async def broadcast(self, payload: dict) -> None:
        stale: List[str] = []
        async with self.lock:
            items = list(self.connections.items())
        for cid, ws in items:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(cid)
        if stale:
            async with self.lock:
                for cid in stale:
                    self.connections.pop(cid, None)
                    self.conn_names.pop(cid, None)
                    self.conn_roles.pop(cid, None)

    async def terminate_room(self, reason: str = "Session ended") -> None:
        if self.ended:
            return
        self.ended = True
        await self.broadcast({"type": "session_ended", "reason": reason})
        async with self.lock:
            sockets = list(self.connections.values())
        for ws in sockets:
            try:
                await ws.close(code=1000, reason=reason[:120])
            except Exception:
                pass
        self.cleanup_disk_and_memory()

        # Schedule process shutdown shortly after response/broadcast flushes
        async def _exit_soon() -> None:
            await asyncio.sleep(0.4)
            os._exit(0)

        asyncio.create_task(_exit_soon())


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def print_terminal_qr(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def sanitize_filename(raw_name: str) -> str:
    base = os.path.basename(raw_name or "upload.bin")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    return (cleaned or "upload.bin")[:120]


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="vanish — temporary self-destructing local chat room")
    parser.add_argument("--minutes", type=int, default=10, help="Room lifetime in minutes")
    parser.add_argument("--max-devices", type=int, default=10, help="Max simultaneous connections")
    parser.add_argument("--port", type=int, default=8000, help="Local port to serve on")
    parser.add_argument("--max-file-mb", type=int, default=25, help="Max size per uploaded file (MB)")
    parser.add_argument("--max-total-mb", type=int, default=300, help="Max total storage for session (MB)")
    args = parser.parse_args()
    return Config(
        minutes=max(1, args.minutes),
        max_devices=max(1, args.max_devices),
        port=args.port,
        max_file_mb=max(1, args.max_file_mb),
        max_total_mb=max(1, args.max_total_mb),
    )


CFG = parse_args()
ROOM = RoomState(CFG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def timer_watcher() -> None:
        while not ROOM.ended:
            await asyncio.sleep(1)
            if time.time() >= ROOM.expires_at:
                await ROOM.terminate_room("Time is up — room vanished.")
                break

    task = asyncio.create_task(timer_watcher())
    try:
        yield
    finally:
        task.cancel()
        ROOM.cleanup_disk_and_memory()


app = FastAPI(title="vanish", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def check_access(token: Optional[str]) -> str:
    if ROOM.ended:
        raise HTTPException(status_code=410, detail="Session ended")
    if token == ROOM.host_token:
        return "host"
    if token == ROOM.join_token:
        return "guest"
    raise HTTPException(status_code=403, detail="Invalid or missing session token")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, token: Optional[str] = Query(default=None)):
    if ROOM.ended:
        return templates.TemplateResponse("expired.html", {"request": request}, status_code=410)
    try:
        role = check_access(token)
    except HTTPException:
        return templates.TemplateResponse("expired.html", {"request": request}, status_code=403)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "role": role,
            "token": token,
            "seconds_left": ROOM.seconds_left,
            "max_file_mb": ROOM.cfg.max_file_mb,
            "max_total_mb": ROOM.cfg.max_total_mb,
            "max_devices": ROOM.cfg.max_devices,
        },
    )


@app.get("/api/meta")
async def meta(token: Optional[str] = Query(default=None)):
    role = check_access(token)
    return {
        "role": role,
        "seconds_left": ROOM.seconds_left,
        "max_file_mb": ROOM.cfg.max_file_mb,
        "max_total_mb": ROOM.cfg.max_total_mb,
        "used_mb": round(ROOM.total_uploaded_bytes / (1024 * 1024), 2),
        "users": list(ROOM.conn_names.values()),
        "history": [m.__dict__ for m in ROOM.messages[-100:]],
    }


@app.post("/api/end")
async def end_session(token: Optional[str] = Query(default=None)):
    role = check_access(token)
    if role != "host":
        raise HTTPException(status_code=403, detail="Host privileges required")
    asyncio.create_task(ROOM.terminate_room("Host ended the session early."))
    return JSONResponse({"status": "terminating"})


@app.get("/api/qr")
async def qr_image(token: Optional[str] = Query(default=None)):
    check_access(token)
    lan_ip = get_lan_ip()
    join_url = f"http://{lan_ip}:{ROOM.cfg.port}/?token={ROOM.join_token}"
    img = qrcode.make(join_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return FileResponse(buf, media_type="image/png")


@app.post("/api/upload")
async def upload_file(
    request: Request,
    token: Optional[str] = Query(default=None),
    sender: str = Form(default="Anonymous"),
    file: UploadFile = File(...),
):
    role = check_access(token)
    if ROOM.ended:
        raise HTTPException(status_code=410, detail="Session ended")

    max_file_bytes = ROOM.cfg.max_file_mb * 1024 * 1024
    max_total_bytes = ROOM.cfg.max_total_mb * 1024 * 1024
    safe_name = sanitize_filename(file.filename or "file.bin")
    file_id = uuid.uuid4().hex[:12]
    dest_path = ROOM.upload_dir / f"{file_id}_{safe_name}"

    written = 0
    chunk_size = 64 * 1024
    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_file_bytes:
                    raise HTTPException(status_code=413, detail="File exceeds per-file limit")
                async with ROOM.lock:
                    if ROOM.total_uploaded_bytes + written > max_total_bytes:
                        raise HTTPException(status_code=413, detail="Session storage limit reached")
                out.write(chunk)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    async with ROOM.lock:
        ROOM.total_uploaded_bytes += written
        file_meta = {
            "id": file_id,
            "name": safe_name,
            "size": written,
            "uploaded_by": (sender or "Anonymous").strip()[:32] or "Anonymous",
        }
        ROOM.files[file_id] = {**file_meta, "path": dest_path}
        msg = ChatMessage(
            id=uuid.uuid4().hex[:10],
            sender=file_meta["uploaded_by"],
            role=role,
            text=f"Shared a file: {safe_name}",
            file=file_meta,
        )
        ROOM.messages.append(msg)

    await ROOM.broadcast({"type": "message", "message": msg.__dict__})
    return {"file": file_meta}


@app.get("/api/files/{file_id}")
async def download_file(file_id: str, token: Optional[str] = Query(default=None)):
    check_access(token)
    meta = ROOM.files.get(file_id)
    if not meta:
        raise HTTPException(status_code=404, detail="File not found or expired")
    path: Path = meta["path"]
    if not path.exists() or not path.resolve().is_relative_to(ROOM.upload_dir.resolve()):
        raise HTTPException(status_code=404, detail="File unavailable")
    return FileResponse(path=path, filename=meta["name"], media_type="application/octet-stream")


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
    name: str = Query(default="Guest"),
):
    try:
        role = check_access(token)
    except HTTPException:
        await websocket.close(code=1008)
        return

    async with ROOM.lock:
        if len(ROOM.connections) >= ROOM.cfg.max_devices:
            await websocket.close(code=1013, reason="Room full")
            return
        cid = uuid.uuid4().hex[:10]
        clean_name = (name or ("Host" if role == "host" else "Guest")).strip()[:32] or "Guest"
        ROOM.connections[cid] = websocket
        ROOM.conn_names[cid] = clean_name
        ROOM.conn_roles[cid] = role

    await websocket.accept()
    await ROOM.broadcast(
        {
            "type": "presence",
            "users": list(ROOM.conn_names.values()),
            "event": f"{clean_name} joined the room",
            "seconds_left": ROOM.seconds_left,
        }
    )

    client_ip = websocket.client.host if websocket.client else "unknown"

    try:
        while not ROOM.ended:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "seconds_left": ROOM.seconds_left})

            elif msg_type == "typing":
                await ROOM.broadcast({"type": "typing", "user": clean_name})

            elif msg_type == "chat":
                raw_text = (data.get("text") or "").strip()
                if not raw_text:
                    continue
                # Simple anti-spam rate limit: max 12 messages per 10 seconds per IP
                now = time.time()
                recent = [t for t in ROOM.ip_msg_timestamps.get(client_ip, []) if now - t < 10]
                if len(recent) >= 12:
                    await websocket.send_json({"type": "error", "message": "Slow down — rate limit reached."})
                    continue
                recent.append(now)
                ROOM.ip_msg_timestamps[client_ip] = recent

                chat_msg = ChatMessage(
                    id=uuid.uuid4().hex[:10],
                    sender=clean_name,
                    role=role,
                    text=raw_text[:2000],
                )
                async with ROOM.lock:
                    ROOM.messages.append(chat_msg)
                await ROOM.broadcast({"type": "message", "message": chat_msg.__dict__})

    except WebSocketDisconnect:
        pass
    finally:
        async with ROOM.lock:
            ROOM.connections.pop(cid, None)
            ROOM.conn_names.pop(cid, None)
            ROOM.conn_roles.pop(cid, None)
        if not ROOM.ended:
            await ROOM.broadcast(
                {
                    "type": "presence",
                    "users": list(ROOM.conn_names.values()),
                    "event": f"{clean_name} left the room",
                    "seconds_left": ROOM.seconds_left,
                }
            )


def main() -> None:
    lan_ip = get_lan_ip()
    join_url = f"http://{lan_ip}:{ROOM.cfg.port}/?token={ROOM.join_token}"
    host_url = f"http://{lan_ip}:{ROOM.cfg.port}/?token={ROOM.host_token}"

    print("\n=== VANISH ROOM READY ===")
    print(f"Join link (share on WiFi): {join_url}")
    print(f"Host link (KEEP PRIVATE):   {host_url}")
    print(f"Lifetime: {ROOM.cfg.minutes}m | Max devices: {ROOM.cfg.max_devices} | Max file: {ROOM.cfg.max_file_mb}MB | Max total: {ROOM.cfg.max_total_mb}MB\n")
    print_terminal_qr(join_url)
    print()

    try:
        uvicorn.run(app, host="0.0.0.0", port=ROOM.cfg.port, log_level="warning")
    finally:
        ROOM.cleanup_disk_and_memory()


if __name__ == "__main__":
    main()