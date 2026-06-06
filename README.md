# SMS IoT Listener Services

Add-on services for the [SMS IoT Platform](https://github.com/adnankhanodoo/sms-iot-deploy).

## Services

| Service | Port | Purpose |
|---------|------|---------|
| PTZ Service | 5002 (HTTPS) | Camera pan/tilt/zoom via MQTT |
| Clip Uploader | 5001 (HTTP) | Download Frigate event snapshots |
| PTT Server | 3000 (HTTPS/WSS) | Push-to-talk browser → speaker |

## Requirements

- Main SMS IoT stack running (`sms-iot-deploy`)
- Docker installed

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/adnankhanodoo/sms-listener/main/install.sh -o /tmp/install.sh && bash /tmp/install.sh
```

## Usage

**PTZ Control:**
```
GET https://DEVICE_IP:5002/<camera>/ptz/<direction>
direction: MOVE_LEFT | MOVE_RIGHT | MOVE_UP | MOVE_DOWN | STOP
```

**Download Clip:**
```
POST http://DEVICE_IP:5001/download_clip
{"event_id": "abc123", "target_host": "frigate:5000"}
```

**PTT:** Open `https://DEVICE_IP:3000` in browser
