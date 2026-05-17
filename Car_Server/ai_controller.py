import logging
import os
import signal
import sys
import threading
import time
import warnings

import cv2
import numpy as np
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

from car_client import CarClient
from fsm_planner import DrivePlanner, PlannerObservation
from perception import VisualObservation, VisionPerception

warnings.filterwarnings("ignore", category=FutureWarning)
werkzeug_log = logging.getLogger("werkzeug")
werkzeug_log.setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

load_dotenv()

PI_IP = os.getenv("CAR_IP", "127.0.0.1")
MAX_CAMERA_FAILURES = 5
FRAME_WIDTH = 320
FRAME_HEIGHT = 240
VIDEO_JPEG_QUALITY = 60

app = Flask(__name__)
CORS(app)

car_client = CarClient(PI_IP)

ai_state = {
    "is_running": False,
    "current_action": "stop",
    "planner_state": "IDLE",
    "distance": 999.0,
    "danger": False,
    "dead_end": False,
    "aeb_triggered": False,
    "camera_ok": False,
    "left_score": 0.0,
    "center_score": 0.0,
    "right_score": 0.0,
    "stuck_count": 0,
    "latest_log": "System initialized",
}

latest_frame = None
frame_lock = threading.Lock()


def update_log(message):
    logger.info(message)
    ai_state["latest_log"] = message


def make_placeholder_frame(title, subtitle=""):
    frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
    cv2.putText(
        frame,
        title,
        (20, 95),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 255),
        2,
    )
    if subtitle:
        cv2.putText(
            frame,
            subtitle,
            (20, 130),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (180, 180, 180),
            1,
        )
    return frame


def overlay_runtime_status(frame, decision, distance_cm, model_ready, camera_fail_count):
    y = 24
    lines = [
        f"STATE: {decision.state.value}",
        f"CMD: {decision.command} speed={decision.speed if decision.speed is not None else 0}",
        f"DIST: {distance_cm:.1f} cm",
        f"MODEL: {'READY' if model_ready else 'OFFLINE'}",
        f"CAM FAILS: {camera_fail_count}",
    ]

    for line in lines:
        cv2.putText(
            frame,
            line,
            (10, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
        )
        y += 18
    return frame


def build_default_visual(frame, title):
    annotated = frame.copy()
    cv2.putText(
        annotated,
        title,
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 200, 255),
        2,
    )
    return VisualObservation(
        annotated_frame=annotated,
        is_blind=False,
        brightness=float(np.mean(frame)),
        left_score=0.0,
        center_score=0.0,
        right_score=0.0,
        turn_direction="right",
        visual_danger=False,
        visual_dead_end=False,
        aeb_triggered=False,
        current_max_area=0,
        area_expansion=0,
        detection_count=0,
    )


def ai_worker():
    global latest_frame

    perception = VisionPerception()
    planner = DrivePlanner(forward_speed=50)
    model = None
    model_ready = False
    prev_max_area = 0
    camera_fail_count = 0
    last_connection_ok = True

    update_log("Loading YOLOv5 model from models/best.pt...")
    try:
        model = perception.load_model()
        model_ready = True
        update_log("Model loaded successfully.")
    except Exception as exc:
        update_log(f"Model load failed: {exc}")

    car_client.send_command("stop", force=True)
    update_log("AI worker thread started.")

    while True:
        timestamp = time.time()
        distance_cm = car_client.get_distance()
        frame = car_client.capture_frame()

        if frame is None:
            camera_fail_count += 1
            ai_state["camera_ok"] = False
            prev_max_area = 0
            frame = make_placeholder_frame("CAMERA OFFLINE", f"failures={camera_fail_count}")
            visual = build_default_visual(frame, "CAMERA OFFLINE")
            is_camera_available = False
        else:
            is_camera_available = True
            camera_fail_count = 0
            ai_state["camera_ok"] = True
            if model_ready:
                visual = perception.analyze(model, frame, prev_max_area)
                prev_max_area = visual.current_max_area
            else:
                prev_max_area = 0
                visual = build_default_visual(frame, "MODEL OFFLINE")

        observation = PlannerObservation(
            ai_enabled=ai_state["is_running"],
            model_ready=model_ready,
            camera_ok=is_camera_available and camera_fail_count < MAX_CAMERA_FAILURES,
            is_blind=visual.is_blind,
            distance_cm=distance_cm,
            left_score=visual.left_score,
            center_score=visual.center_score,
            right_score=visual.right_score,
            visual_danger=visual.visual_danger,
            visual_dead_end=visual.visual_dead_end,
            aeb_triggered=visual.aeb_triggered,
            timestamp=timestamp,
        )
        decision = planner.plan(observation)

        success, sent = car_client.send_command(
            decision.command,
            speed=decision.speed,
        )
        if not success and last_connection_ok:
            update_log(f"Lost connection to Pi while sending '{decision.command}'")
            last_connection_ok = False
        elif success:
            last_connection_ok = True

        ai_state["current_action"] = decision.command
        ai_state["planner_state"] = decision.state.value
        ai_state["distance"] = distance_cm
        ai_state["danger"] = decision.danger
        ai_state["dead_end"] = decision.dead_end
        ai_state["aeb_triggered"] = decision.aeb_triggered
        ai_state["left_score"] = round(visual.left_score, 3)
        ai_state["center_score"] = round(visual.center_score, 3)
        ai_state["right_score"] = round(visual.right_score, 3)
        ai_state["stuck_count"] = planner.stuck_count

        logger.info(
            "[PLAN] distance_cm=%.1f left_score=%.2f center_score=%.2f "
            "right_score=%.2f danger=%s dead_end=%s stuck_count=%d "
            "command=%s speed=%s",
            distance_cm,
            visual.left_score,
            visual.center_score,
            visual.right_score,
            decision.danger,
            decision.dead_end,
            planner.stuck_count,
            decision.command,
            decision.speed if decision.speed is not None else "None",
        )

        annotated = overlay_runtime_status(
            visual.annotated_frame.copy(),
            decision,
            distance_cm,
            model_ready,
            camera_fail_count,
        )
        with frame_lock:
            latest_frame = annotated

        if decision.transition_log:
            update_log(
                f"[FSM] {decision.transition_log} | reason={decision.reason} | sent={sent}"
            )

        if not is_camera_available and camera_fail_count >= MAX_CAMERA_FAILURES:
            time.sleep(0.25)
        else:
            time.sleep(0.05)


@app.route("/")
def index():
    return render_template(
        "index.html",
        pi_ip=PI_IP,
        snapshot_url=car_client.snapshot_url,
    )


def generate_video():
    while True:
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None
        if frame is not None:
            ret, buffer = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, VIDEO_JPEG_QUALITY],
            )
            if ret:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + buffer.tobytes()
                    + b"\r\n"
                )
        time.sleep(0.05)


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_video(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/status")
def get_status():
    return jsonify(ai_state)


@app.route("/api/toggle_ai", methods=["POST"])
def toggle_ai():
    data = request.json or {}
    if "state" not in data:
        return jsonify({"status": "error"}), 400

    ai_state["is_running"] = bool(data["state"])
    if ai_state["is_running"]:
        update_log("User STARTED the AI controller.")
    else:
        car_client.send_command("stop", force=True)
        update_log("User STOPPED the AI controller.")

    return jsonify({"status": "success", "is_running": ai_state["is_running"]})


@app.route("/api/emergency_stop", methods=["POST"])
def emergency_stop():
    ai_state["is_running"] = False
    car_client.send_command("stop", force=True)
    update_log("EMERGENCY STOP TRIGGERED BY USER!")
    return jsonify({"status": "success"})


def signal_handler(sig, frame_signal):
    logger.info("Received exit signal.")
    car_client.send_command("stop", force=True)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    worker = threading.Thread(target=ai_worker, daemon=True)
    worker.start()

    logger.info("=" * 50)
    logger.info("WEB GUI IS RUNNING")
    logger.info("Open http://127.0.0.1:8080 in your browser")
    logger.info("=" * 50)
    app.run(host="0.0.0.0", port=8080, threaded=True, use_reloader=False)
