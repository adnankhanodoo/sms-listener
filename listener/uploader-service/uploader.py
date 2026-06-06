"""
uploader.py  —  Frigate clip/snapshot downloader service (Docker edition)
Flask HTTP server on port 5001.

POST /download_clip
  Body: {"event_id": "...", "target_host": "frigate:5000"}
  Downloads a snapshot/clip from Frigate and saves to /downloads/

GET  /health
GET  /.well-known/acme-challenge/<token>   (Let's Encrypt passthrough)
"""

import os
import logging
from datetime import datetime

import requests
from flask import Flask, request, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [UPLOADER] %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── Config ─────────────────────────────────────────────────
# Default Frigate host — overridden by POST body per-request
DEFAULT_FRIGATE_HOST = os.getenv("FRIGATE_HOST", "frigate:5000")

# Where downloaded files land (bind-mount this volume)
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Suppress InsecureRequestWarning
requests.packages.urllib3.disable_warnings()


# ── Helpers ────────────────────────────────────────────────

def download_clip(target_host: str, event_id: str) -> dict:
    """Download a Frigate event snapshot and save it to DOWNLOAD_DIR."""
    clip_url = f"http://{target_host}/api/events/{event_id}/snapshot.jpg"
    log.info("Downloading: %s", clip_url)

    try:
        resp = requests.get(clip_url, stream=True, timeout=60, verify=False)

        if resp.status_code != 200:
            return {"success": False,
                    "message": f"Frigate returned HTTP {resp.status_code}"}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = f"{event_id}_{timestamp}.jpg"
        file_path = os.path.join(DOWNLOAD_DIR, filename)

        with open(file_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    fh.write(chunk)

        log.info("Saved → %s", file_path)
        return {
            "success":   True,
            "file_path": file_path,
            "filename":  filename,
            "clip_url":  clip_url,
        }

    except Exception as exc:
        log.error("Download failed: %s", exc)
        return {"success": False, "message": str(exc)}


# ── Routes ─────────────────────────────────────────────────

@app.get("/.well-known/acme-challenge/<token>")
def acme_challenge(token: str):
    """Let's Encrypt HTTP-01 challenge passthrough."""
    challenge = os.getenv(
        "ACME_CHALLENGE",
        f"{token}.zERTCw50zeIoluNsk6srTjOEj92819pDi6LESTNfhwU"
    )
    return challenge, 200, {"Content-Type": "text/plain"}


@app.post("/download_clip")
def handle_download():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    event_id    = data.get("event_id")
    target_host = data.get("target_host", DEFAULT_FRIGATE_HOST)

    if not event_id:
        return jsonify({"success": False, "message": "Missing event_id"}), 400

    result = download_clip(target_host=target_host, event_id=event_id)
    return jsonify(result), (200 if result["success"] else 500)


@app.get("/health")
def health():
    return jsonify({"status": "ok",
                    "download_dir": DOWNLOAD_DIR}), 200


if __name__ == "__main__":
    log.info("Uploader service starting on :5001")
    app.run(host="0.0.0.0", port=5001, debug=False)
