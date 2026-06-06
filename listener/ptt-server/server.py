"""
server.py  —  Push-to-Talk server (Docker / Linux edition)
WebSocket server on port 3000 (HTTPS/WSS).

Browser mic → WebSocket (raw PCM s16le 48kHz mono)
           → ffplay → ALSA / PulseAudio speaker on the Docker host

Requirements (installed in Dockerfile):
  - ffmpeg (provides ffplay)
  - aiohttp
  - PulseAudio or ALSA on the host (socket passed in via volume)

SSL certs mounted at /certs/ inside the container.
"""

import asyncio
import json
import logging
import mimetypes
import os
import platform
import socket
import subprocess
import threading
import uuid
import ssl
from pathlib import Path

from aiohttp import web
import aiohttp

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

PORT       = int(os.getenv("PTT_PORT", 3000))
STATIC_DIR = Path(__file__).parent / "static"

SSL_CERTFILE = os.getenv("SSL_CERTFILE", "/certs/fullchain.pem")
SSL_KEYFILE  = os.getenv("SSL_KEYFILE",  "/certs/privkey.pem")

# Audio output device — override via env if needed
# Examples:  "default"  "pulse"  "hw:0,0"
ALSA_DEVICE = os.getenv("ALSA_DEVICE", "default")

# ── active sessions ────────────────────────────────────────
sessions: dict[str, dict] = {}
sessions_lock = threading.Lock()


# ── ffplay launcher (Linux ALSA/PulseAudio) ───────────────
def spawn_ffplay() -> subprocess.Popen:
    """
    Spawn ffplay reading raw s16le PCM from stdin
    and writing to the ALSA/PulseAudio default output.
    """
    cmd = [
        "ffplay",
        "-hide_banner",
        "-loglevel", "warning",
        "-nodisp",
        "-autoexit",
        "-f",        "s16le",
        "-ar",       "48000",
        "-ch_layout", "mono",
        "-i",        "pipe:0",
    ]

    env = os.environ.copy()

    # If PulseAudio socket is forwarded from host, point to it
    pulse_sock = os.getenv("PULSE_SERVER", "")
    if pulse_sock:
        env["PULSE_SERVER"] = pulse_sock

    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )


def end_session(session_id: str):
    with sessions_lock:
        s = sessions.pop(session_id, None)
    if not s:
        return
    ff: subprocess.Popen = s["ff"]
    try:
        if ff.stdin:
            ff.stdin.close()
        ff.terminate()
    except Exception:
        pass
    log.info(f"[{session_id[:8]}] Session ended")


def monitor_ffplay(
    session_id: str,
    ff: subprocess.Popen,
    ws: web.WebSocketResponse,
    loop: asyncio.AbstractEventLoop,
):
    """Background thread: pipe ffplay stderr → log and watch for errors."""
    for raw in ff.stderr:
        text = raw.decode(errors="replace").strip()
        log.info(f"[{session_id[:8]}] ffplay: {text}")
        if any(k in text for k in ("No such device", "ALSA", "pulse")):
            asyncio.run_coroutine_threadsafe(
                ws.send_str(json.dumps({
                    "type": "error",
                    "message": f"Audio device error: {text}"
                })),
                loop,
            )
    code = ff.wait()
    log.info(f"[{session_id[:8]}] ffplay exited ({code})")
    with sessions_lock:
        sessions.pop(session_id, None)


# ── WebSocket handler ──────────────────────────────────────
async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws   = web.WebSocketResponse()
    await ws.prepare(request)

    session_id = str(uuid.uuid4())
    loop       = asyncio.get_event_loop()
    log.info(f"[{session_id[:8]}] Client connected from {request.remote}")

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.BINARY:
                # Raw PCM → pipe into ffplay stdin
                with sessions_lock:
                    s = sessions.get(session_id)
                if s:
                    ff: subprocess.Popen = s["ff"]
                    try:
                        if ff.stdin and not ff.stdin.closed:
                            ff.stdin.write(msg.data)
                            ff.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass

            elif msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    ctrl = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                if ctrl.get("type") == "ptt_start":
                    with sessions_lock:
                        if session_id in sessions:
                            continue   # already active

                    log.info(f"[{session_id[:8]}] PTT started")

                    try:
                        ff = spawn_ffplay()
                    except FileNotFoundError:
                        await ws.send_str(json.dumps({
                            "type":    "error",
                            "message": "ffplay not found — ensure ffmpeg is installed in the container",
                        }))
                        continue

                    with sessions_lock:
                        sessions[session_id] = {"ff": ff, "ws": ws}

                    threading.Thread(
                        target=monitor_ffplay,
                        args=(session_id, ff, ws, loop),
                        daemon=True,
                    ).start()

                    await ws.send_str(json.dumps({"type": "ptt_started"}))

                elif ctrl.get("type") == "ptt_stop":
                    end_session(session_id)
                    await ws.send_str(json.dumps({"type": "ptt_stopped"}))

            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                break

    finally:
        log.info(f"[{session_id[:8]}] Client disconnected")
        end_session(session_id)

    return ws


# ── Static file handler ────────────────────────────────────
async def static_handler(request: web.Request) -> web.Response:
    rel      = request.match_info.get("path", "") or "index.html"
    filepath = (STATIC_DIR / rel).resolve()

    try:
        filepath.relative_to(STATIC_DIR.resolve())
    except ValueError:
        raise web.HTTPForbidden()

    if not filepath.exists() or not filepath.is_file():
        raise web.HTTPNotFound()

    mime, _ = mimetypes.guess_type(str(filepath))
    return web.Response(
        body=filepath.read_bytes(),
        content_type=mime or "application/octet-stream",
    )


# ── /info endpoint ─────────────────────────────────────────
async def info_handler(request: web.Request) -> web.Response:
    return web.json_response({
        "platform":       platform.system().lower(),
        "hostname":       socket.gethostname(),
        "activeSessions": len(sessions),
        "alsa_device":    ALSA_DEVICE,
    })


# ── Helpers ────────────────────────────────────────────────
def get_local_ips() -> list[str]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return [s.getsockname()[0]]
    except Exception:
        return []


# ── Main ───────────────────────────────────────────────────
async def main():
    web_app = web.Application()
    web_app.router.add_get("/ws",         ws_handler)
    web_app.router.add_get("/info",       info_handler)
    web_app.router.add_get("/",           static_handler)
    web_app.router.add_get("/{path:.*}",  static_handler)

    runner = web.AppRunner(web_app)
    await runner.setup()

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(SSL_CERTFILE, SSL_KEYFILE)

    site = web.TCPSite(runner, "0.0.0.0", PORT, ssl_context=ssl_ctx)
    await site.start()

    ips = get_local_ips()
    log.info("\n✓ PTT server running (Docker/Linux)")
    log.info(f"  Local:   https://localhost:{PORT}")
    for ip in ips:
        log.info(f"  Network: https://{ip}:{PORT}")
    log.info(f"  WS:      wss://localhost:{PORT}/ws")
    log.info(f"  Audio:   ALSA device = {ALSA_DEVICE}\n")

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
