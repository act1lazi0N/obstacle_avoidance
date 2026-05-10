# =========================================================
# File: ai_controller.py
# =========================================================

import os
import time
import warnings
import signal
import sys
import cv2
import requests
import torch.hub
import pathlib
import logging
import numpy as np
import threading

from dotenv import load_dotenv
from flask import Flask, render_template, Response, jsonify, request
from flask_cors import CORS

# =========================================================
# WARNINGS / LOGGING
# =========================================================

warnings.filterwarnings("ignore", category=FutureWarning)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)

# =========================================================
# ENV
# =========================================================

load_dotenv()

PI_IP = os.getenv("CAR_IP", "127.0.0.1")

SNAPSHOT_URL = f"http://{PI_IP}:5000/snapshot"
CONTROL_URL = f"http://{PI_IP}:5000/control"

DISTANCE_URL = f"http://{PI_IP}:5000/distance"
REAR_DISTANCE_URL = f"http://{PI_IP}:5000/rear_distance"

# =========================================================
# CONFIG
# =========================================================

TURN_DURATION = 0.8
POST_DEADEND_TURN_DURATION = 1.0

DANGER_AREA_THRESHOLD = 5000
DEAD_END_AREA_THRESHOLD = 25000

BRIGHTNESS_THRESHOLD = 15

MAX_CAMERA_FAILURES = 5

FRONT_STOP_DISTANCE = 18
FRONT_DANGER_DISTANCE = 30

REAR_STOP_DISTANCE = 15

COMMAND_INTERVAL = 0.25

ESCAPE_BACKWARD_TIME = 1.0
ESCAPE_TURN_TIME = 1.2

USE_ULTRASONIC = True

TTC_EXPANSION_THRESHOLD = 8000

# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)
CORS(app)

# =========================================================
# GLOBAL STATE
# =========================================================

ai_state = {
    "is_running": False,
    "current_action": "stop",

    "front_distance": 999.0,
    "rear_distance": 999.0,

    "danger": False,
    "dead_end": False,
    "aeb_triggered": False,

    "camera_ok": False,

    "latest_log": "System initialized"
}

latest_frame = None

frame_lock = threading.Lock()

last_command = None
last_command_time = 0

# =========================================================
# LOG HELPER
# =========================================================

def update_log(msg):

    logger.info(msg)

    ai_state["latest_log"] = msg

# =========================================================
# YOLO MODEL
# =========================================================

def load_model():

    update_log("Loading YOLOv5 model...")

    temp = pathlib.PosixPath

    try:

        pathlib.PosixPath = pathlib.WindowsPath

        # LOCAL YOLOv5 RECOMMENDED
        model = torch.hub.load(
            './yolov5',
            'custom',
            path='models/best.pt',
            source='local'
        )

        model.conf = 0.45

    finally:

        pathlib.PosixPath = temp

    update_log("Model loaded successfully!")

    return model

# =========================================================
# SEND COMMAND
# =========================================================

def send_command(cmd, force=False):

    global last_command
    global last_command_time

    now = time.time()

    # Prevent command spam
    if (
        not force
        and cmd == last_command
        and (now - last_command_time) < COMMAND_INTERVAL
    ):
        return True

    try:

        resp = requests.get(
            CONTROL_URL,
            params={'cmd': cmd},
            timeout=0.5
        )

        if resp.status_code == 200:

            last_command = cmd
            last_command_time = now

            return True

        logger.warning(
            f"Command rejected: {cmd} ({resp.status_code})"
        )

        return False

    except requests.exceptions.ConnectionError:

        logger.error(
            f"Lost connection while sending '{cmd}'"
        )

        return False

    except Exception as e:

        logger.error(f"Command '{cmd}' failed: {e}")

        return False

# =========================================================
# CAMERA
# =========================================================

def capture_frame():

    try:

        resp = requests.get(
            SNAPSHOT_URL,
            timeout=1
        )

        img_arr = np.array(
            bytearray(resp.content),
            dtype=np.uint8
        )

        frame = cv2.imdecode(
            img_arr,
            cv2.IMREAD_COLOR
        )

        return frame

    except:

        return None

# =========================================================
# ULTRASONIC
# =========================================================

def get_front_distance():

    try:

        resp = requests.get(
            DISTANCE_URL,
            timeout=0.2
        )

        return float(resp.text)

    except:

        return 999

def get_rear_distance():

    try:

        resp = requests.get(
            REAR_DISTANCE_URL,
            timeout=0.2
        )

        return float(resp.text)

    except:

        return 999

# =========================================================
# BRIGHTNESS CHECK
# =========================================================

def check_brightness(frame):

    brightness = np.mean(frame)

    return brightness >= BRIGHTNESS_THRESHOLD

# =========================================================
# DETECT OBSTACLES
# =========================================================

def detect_obstacles(model, frame, prev_max_area):

    img_rgb = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2RGB
    )

    results = model(img_rgb)

    df = results.pandas().xyxy[0]

    frame_center_x = frame.shape[1] / 2

    danger = False
    dead_end = False

    turn_direction = 'right'

    aeb_trigger = False

    current_max_area = 0

    if not df.empty:

        df = df.copy()

        df['area'] = (
            (df['xmax'] - df['xmin'])
            *
            (df['ymax'] - df['ymin'])
        )

        df = df.sort_values(
            'area',
            ascending=False
        ).reset_index(drop=True)

        for _, row in df.iterrows():

            x1 = int(row['xmin'])
            y1 = int(row['ymin'])

            x2 = int(row['xmax'])
            y2 = int(row['ymax'])

            label = row['name']

            conf = row['confidence']

            area = int(row['area'])

            current_max_area = max(
                current_max_area,
                area
            )

            # BOX
            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                f"{label} {conf:.0%} A:{area}",
                (x1, y2 + 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 0),
                1
            )

            obj_center_x = (x1 + x2) / 2

            if obj_center_x < frame_center_x:

                turn_direction = 'right'

            else:

                turn_direction = 'left'

            # DANGER
            if area > DEAD_END_AREA_THRESHOLD:

                dead_end = True

                update_log(
                    f"DEAD END: {label} area={area}"
                )

                break

            elif area > DANGER_AREA_THRESHOLD:

                danger = True

                update_log(
                    f"DANGER: {label} area={area}"
                )

                break

    area_expansion = (
        current_max_area - prev_max_area
    )

    if (
        prev_max_area > 0
        and area_expansion > TTC_EXPANSION_THRESHOLD
    ):

        aeb_trigger = True

        cv2.putText(
            frame,
            "AEB BRAKE",
            (20, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            3
        )

    return (
        danger,
        turn_direction,
        dead_end,
        aeb_trigger,
        current_max_area,
        frame
    )

# =========================================================
# AI WORKER
# =========================================================

def ai_worker():

    global latest_frame

    model = None

    try:

        model = load_model()

    except Exception as e:

        update_log(f"Model load failed: {e}")

        update_log(
            "PASSTHROUGH MODE ENABLED"
        )

    current_action = "stop"

    avoidance_timer = 0

    camera_fail_count = 0

    prev_max_area = 0

    needs_escape_turn = False

    last_turn_direction = "right"

    send_command('stop', force=True)

    update_log("AI Worker started.")

    while True:

        try:

            # =====================================================
            # CAMERA
            # =====================================================

            frame = capture_frame()

            if frame is None:

                ai_state["camera_ok"] = False

                camera_fail_count += 1

                if (
                    camera_fail_count
                    >= MAX_CAMERA_FAILURES
                ):

                    send_command(
                        'stop',
                        force=True
                    )

                    current_action = "stop"

                    update_log(
                        "Camera disconnected!"
                    )

                time.sleep(0.5)

                continue

            ai_state["camera_ok"] = True

            camera_fail_count = 0

            # =====================================================
            # BRIGHTNESS CHECK
            # =====================================================

            if not check_brightness(frame):

                send_command('stop', force=True)

                current_action = "stop"

                cv2.putText(
                    frame,
                    "CAMERA BLIND",
                    (50, 100),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 0, 255),
                    2
                )

                with frame_lock:
                    latest_frame = frame

                time.sleep(0.1)

                continue

            # =====================================================
            # SENSOR FUSION
            # =====================================================

            front_distance = 999
            rear_distance = 999

            if USE_ULTRASONIC:

                front_distance = get_front_distance()

                rear_distance = get_rear_distance()

            ai_state["front_distance"] = front_distance
            ai_state["rear_distance"] = rear_distance

            # =====================================================
            # NO MODEL
            # =====================================================

            if model is None:

                cv2.putText(
                    frame,
                    "NO AI MODEL",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2
                )

                with frame_lock:
                    latest_frame = frame

                time.sleep(0.05)

                continue

            # =====================================================
            # DETECT
            # =====================================================

            (
                danger,
                turn_direction,
                visual_dead_end,
                aeb_trigger,
                current_max_area,
                annotated_frame
            ) = detect_obstacles(
                model,
                frame,
                prev_max_area
            )

            prev_max_area = current_max_area

            # =====================================================
            # SENSOR + AI FUSION
            # =====================================================

            is_dead_end = (
                visual_dead_end
                or front_distance < FRONT_STOP_DISTANCE
            )

            is_danger = (
                danger
                or front_distance < FRONT_DANGER_DISTANCE
            )

            ai_state["danger"] = is_danger
            ai_state["dead_end"] = is_dead_end
            ai_state["aeb_triggered"] = aeb_trigger

            # =====================================================
            # HUD
            # =====================================================

            cv2.putText(
                annotated_frame,
                f"Front: {front_distance:.1f} cm",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

            cv2.putText(
                annotated_frame,
                f"Rear: {rear_distance:.1f} cm",
                (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 0),
                2
            )

            cv2.putText(
                annotated_frame,
                f"Action: {current_action}",
                (10, 75),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 200, 255),
                2
            )

            with frame_lock:
                latest_frame = annotated_frame

            # =====================================================
            # AI PAUSED
            # =====================================================

            if not ai_state["is_running"]:

                if current_action != "stop":

                    send_command(
                        "stop",
                        force=True
                    )

                    current_action = "stop"

                    update_log(
                        "AI paused."
                    )

                ai_state["current_action"] = "paused"

                time.sleep(0.2)

                continue

            # =====================================================
            # CONTROL
            # =====================================================

            if time.time() >= avoidance_timer:

                # AEB
                if aeb_trigger:

                    update_log(
                        "AEB TRIGGERED"
                    )

                    send_command(
                        'stop',
                        force=True
                    )

                    avoidance_timer = (
                        time.time() + 1.5
                    )

                    current_action = "AEB stop"

                # DEAD END
                elif is_dead_end:

                    update_log(
                        f"DEAD END | Front={front_distance:.1f}cm"
                    )

                    send_command(
                        'stop',
                        force=True
                    )

                    time.sleep(0.3)

                    # Reverse possible
                    if rear_distance > REAR_STOP_DISTANCE:

                        update_log(
                            f"Reversing | Rear={rear_distance:.1f}cm"
                        )

                        send_command(
                            'backward',
                            force=True
                        )

                        avoidance_timer = (
                            time.time()
                            + ESCAPE_BACKWARD_TIME
                        )

                        current_action = "backward"

                        needs_escape_turn = True

                    else:

                        update_log(
                            "Rear blocked -> rotating"
                        )

                        turn_direction = (
                            "left"
                            if last_turn_direction == "right"
                            else "right"
                        )

                        send_command(
                            turn_direction,
                            force=True
                        )

                        last_turn_direction = turn_direction

                        avoidance_timer = (
                            time.time()
                            + ESCAPE_TURN_TIME
                        )

                        current_action = (
                            f"rotate {turn_direction}"
                        )

                # ESCAPE TURN
                elif needs_escape_turn:

                    update_log(
                        f"Escape turn {last_turn_direction}"
                    )

                    send_command(
                        last_turn_direction,
                        force=True
                    )

                    avoidance_timer = (
                        time.time()
                        + POST_DEADEND_TURN_DURATION
                    )

                    current_action = (
                        f"escape {last_turn_direction}"
                    )

                    needs_escape_turn = False

                # NORMAL DANGER
                elif is_danger:

                    if turn_direction == last_turn_direction:

                        turn_direction = (
                            "left"
                            if turn_direction == "right"
                            else "right"
                        )

                    last_turn_direction = turn_direction

                    update_log(
                        f"Obstacle -> {turn_direction.upper()}"
                    )

                    send_command(
                        turn_direction,
                        force=True
                    )

                    avoidance_timer = (
                        time.time()
                        + TURN_DURATION
                    )

                    current_action = (
                        f"avoiding {turn_direction}"
                    )

                # CLEAR PATH
                else:

                    if current_action != "go":

                        update_log(
                            "Clear path"
                        )

                        send_command(
                            "go",
                            force=True
                        )

                        current_action = "go"

            ai_state["current_action"] = current_action

            time.sleep(0.03)

        except Exception as e:

            update_log(f"System error: {e}")

            send_command(
                'stop',
                force=True
            )

            time.sleep(1)

# =========================================================
# FLASK ROUTES
# =========================================================

@app.route('/')
def index():

    return render_template(
        'index.html',
        pi_ip=PI_IP,
        snapshot_url=SNAPSHOT_URL
    )

# =========================================================
# VIDEO STREAM
# =========================================================

def generate_video():

    while True:

        with frame_lock:

            if latest_frame is not None:

                ret, buffer = cv2.imencode(
                    '.jpg',
                    latest_frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 60]
                )

                if ret:

                    frame_bytes = buffer.tobytes()

                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n'
                        + frame_bytes
                        + b'\r\n'
                    )

        time.sleep(0.05)

@app.route('/video_feed')
def video_feed():

    return Response(
        generate_video(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

# =========================================================
# API
# =========================================================

@app.route('/api/status')
def get_status():

    return jsonify(ai_state)

@app.route('/api/toggle_ai', methods=['POST'])
def toggle_ai():

    data = request.json

    if 'state' in data:

        ai_state['is_running'] = bool(data['state'])

        action = (
            "STARTED"
            if ai_state['is_running']
            else "STOPPED"
        )

        update_log(
            f"User {action} AI"
        )

        return jsonify({
            "status": "success",
            "is_running": ai_state['is_running']
        })

    return jsonify({
        "status": "error"
    }), 400

@app.route('/api/emergency_stop', methods=['POST'])
def emergency_stop():

    ai_state['is_running'] = False

    send_command(
        "stop",
        force=True
    )

    update_log(
        "EMERGENCY STOP"
    )

    return jsonify({
        "status": "success"
    })

# =========================================================
# MAIN
# =========================================================

if __name__ == '__main__':

    def signal_handler(sig, frame_signal):

        logger.info("Exit signal received")

        send_command(
            'stop',
            force=True
        )

        time.sleep(0.3)

        sys.exit(0)

    signal.signal(
        signal.SIGINT,
        signal_handler
    )

    # AI THREAD
    t = threading.Thread(
        target=ai_worker,
        daemon=True
    )

    t.start()

    logger.info("=" * 50)
    logger.info("WEB GUI RUNNING")
    logger.info("Open http://127.0.0.1:8081")
    logger.info("=" * 50)

    app.run(
        host='0.0.0.0',
        port=8081,
        threaded=True,
        use_reloader=False
    )
