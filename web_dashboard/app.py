"""
AutoCar — Web Dashboard (Flask)

Serves the monitoring GUI and provides API endpoints.
Connects to MQTT to receive live state updates from Pi and AI Brain.

Endpoints:
    GET  /              → Dashboard HTML
    GET  /api/state     → JSON system state
    POST /api/estop     → Emergency stop
    POST /api/reset     → Reset from E-STOP
    POST /api/ai/toggle → Toggle AI on/off

Usage:
    python -m web_dashboard.app
"""

import signal
import sys
import logging
import time
from flask import Flask, render_template, jsonify, request, Response

from shared.config import (
    DASHBOARD_PORT, DASHBOARD_HOST,
    Topics,
)
from shared.mqtt_client import AutoCarMQTT
from web_dashboard.mqtt_listener import DashboardState, DashboardMQTTListener

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Globals — initialized in main()
dashboard_state = DashboardState()
mqtt_client: AutoCarMQTT = None


# ── Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the dashboard page."""
    return render_template(
        "index.html",
        mjpeg_url="/video_feed",
    )


@app.route("/video_feed")
def video_feed():
    """Stream latest MQTT camera frames as MJPEG for the dashboard."""

    def generate():
        while True:
            frame = dashboard_state.wait_for_camera_frame(timeout=2.0)
            if frame is None:
                time.sleep(0.1)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-cache\r\n\r\n"
                + frame
                + b"\r\n"
            )

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/state")
def api_state():
    """Return current system state as JSON."""
    return jsonify(dashboard_state.to_dict())


@app.route("/api/estop", methods=["POST"])
def api_estop():
    """Send emergency stop to the Pi."""
    mqtt_client.publish_empty(Topics.CONTROL_EMERGENCY_STOP, qos=1)
    logger.warning("[DASHBOARD] Emergency stop sent!")
    return jsonify({"status": "ok", "action": "emergency_stop"})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Reset Pi from emergency stop."""
    mqtt_client.publish_json(
        Topics.COMMAND_MOTOR,
        {"action": "reset", "speed": 0, "steer": 0},
        qos=1,
    )
    logger.info("[DASHBOARD] Reset command sent.")
    return jsonify({"status": "ok", "action": "reset"})


@app.route("/api/ai/toggle", methods=["POST"])
def api_ai_toggle():
    """Toggle AI brain on/off."""
    data = request.get_json(silent=True) or {}
    mqtt_client.publish_json(
        Topics.CONTROL_AI_TOGGLE,
        {"enabled": data.get("enabled", True)},
        qos=1,
    )
    return jsonify({"status": "ok", "action": "ai_toggle"})


# ── Main ──────────────────────────────────────────────────────────

def main():
    global mqtt_client

    logger.info("=" * 50)
    logger.info("AUTOCAR WEB DASHBOARD — Starting...")
    logger.info("=" * 50)

    # Initialize MQTT
    mqtt_client = AutoCarMQTT(client_id="web_dashboard")
    try:
        mqtt_client.connect()
    except ConnectionError as e:
        logger.critical(f"MQTT connection failed: {e}")
        sys.exit(1)

    # Start listener
    listener = DashboardMQTTListener(mqtt_client, dashboard_state)
    listener.start()

    # Signal handlers
    def cleanup(sig=None, frame=None):
        logger.info("Shutting down Dashboard...")
        mqtt_client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    logger.info(f"Dashboard: http://localhost:{DASHBOARD_PORT}")
    logger.info(f"Video feed: http://localhost:{DASHBOARD_PORT}/video_feed")

    # Run Flask
    app.run(
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
