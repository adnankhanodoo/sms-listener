"""
ptz.py  —  PTZ control service (Docker edition)
Flask HTTPS server on port 5002.
Sends MQTT PTZ commands to Frigate camera topics.

Route:  GET /<camera>/ptz/<direction>
  direction: MOVE_LEFT | MOVE_RIGHT | MOVE_UP | MOVE_DOWN | STOP

SSL certs are mounted at /certs/ inside the container.
"""

import os
import ssl
import time
import logging

import paho.mqtt.client as mqtt
from flask import Flask, jsonify
from flask_cors import CORS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PTZ] %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ── Config from env ────────────────────────────────────────
FRIGATE_URL   = os.getenv("FRIGATE_MQTT_HOST",  "mosquitto")
FRIGATE_PORT  = int(os.getenv("FRIGATE_MQTT_PORT", 1883))
FRIGATE_TOPIC = os.getenv("FRIGATE_TOPIC",      "frigate-165/")

SSL_CERTFILE  = os.getenv("SSL_CERTFILE", "/certs/fullchain.pem")
SSL_KEYFILE   = os.getenv("SSL_KEYFILE",  "/certs/privkey.pem")

VALID_DIRECTIONS = {"MOVE_LEFT", "MOVE_RIGHT", "MOVE_UP", "MOVE_DOWN", "STOP"}


@app.route("/<camera>/ptz/<direction>", methods=["GET"])
def handle_camera_control(camera: str, direction: str):
    direction = direction.upper()

    if direction not in VALID_DIRECTIONS:
        return jsonify({
            "success": False,
            "message": f"Invalid direction '{direction}'. "
                       f"Valid: {sorted(VALID_DIRECTIONS)}"
        }), 400

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.connect(FRIGATE_URL, FRIGATE_PORT, keepalive=10)

        move_topic = FRIGATE_TOPIC + camera + "/ptz"

        client.publish(move_topic, direction)
        log.info("Published %s → %s", direction, move_topic)

        if direction != "STOP":
            time.sleep(1)
            client.publish(move_topic, "STOP")
            log.info("Published STOP → %s", move_topic)

        client.disconnect()

        return jsonify({"success": True, "message": "ok",
                        "camera": camera, "direction": direction}), 200

    except Exception as exc:
        log.error("PTZ error: %s", exc)
        return jsonify({"success": False, "message": str(exc)}), 500


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    # Build SSL context
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(SSL_CERTFILE, SSL_KEYFILE)

    log.info("PTZ service starting on :5002 (HTTPS)")
    app.run(host="0.0.0.0", port=5002, debug=False, ssl_context=ctx)
