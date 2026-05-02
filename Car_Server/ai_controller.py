# File: ai_controller.py
# Environment: Local Server / Cloud (runs on personal computer or server)
# Description: AI controller using YOLOv5 combined with Sensor Fusion (Ultrasonic)
#              to detect obstacles and control the Raspberry Pi car via HTTP API.
#              Provides a Flask Web GUI to view camera and control the car.
# -----------------------------------------------------------------------
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

warnings.filterwarnings("ignore", category=FutureWarning)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

load_dotenv()  # Load environment variables from .env file

# If CAR_IP is not set in .env, default to "127.0.0.1" for local testing
PI_IP = os.getenv("CAR_IP", "127.0.0.1")
SNAPSHOT_URL = f"http://{PI_IP}:5000/snapshot"
CONTROL_URL = f"http://{PI_IP}:5000/control"
DISTANCE_URL = f"http://{PI_IP}:5000/distance"

TURN_DURATION = 0.8
POST_DEADEND_TURN_DURATION = 1.0
DANGER_AREA_THRESHOLD = 5000
DEAD_END_AREA_THRESHOLD = 25000
BRIGHTNESS_THRESHOLD = 15
MAX_CAMERA_FAILURES = 5

USE_ULTRASONIC = False
TTC_EXPANSION_THRESHOLD = 8000


# === FLASK APP SETUP ===
app = Flask(__name__)
CORS(app)

# Global states for GUI
ai_state = {
    "is_running": False,
    "current_action": "stop",
    "distance": 999.0,
    "danger": False,
    "dead_end": False,
    "aeb_triggered": False,
    "camera_ok": False,
    "latest_log": "System initialized"
}

latest_frame = None
frame_lock = threading.Lock()

def update_log(msg):
    logger.info(msg)
    ai_state["latest_log"] = msg

def load_model():
    update_log("Loading YOLOv5 model from models/best.pt...")
    temp = pathlib.PosixPath
    try:
        pathlib.PosixPath = pathlib.WindowsPath
        model = torch.hub.load('ultralytics/yolov5', 'custom', path='models/best.pt', force_reload=True)
        model.conf = 0.6
    finally:
        pathlib.PosixPath = temp
    update_log("Model loaded successfully!")
    return model


def send_command(cmd):
    try:
        requests.get(CONTROL_URL, params={'cmd': cmd}, timeout=0.5)
        return True
    except requests.exceptions.ConnectionError:
        logger.error(f"Lost connection to Pi while sending command '{cmd}'!")
        return False
    except Exception as e:
        logger.error(f"Command '{cmd}' failed: {e}")
        return False


def capture_frame():
    try:
        resp = requests.get(SNAPSHOT_URL, timeout=1)
        img_arr = np.array(bytearray(resp.content), dtype=np.uint8)
        frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        return frame
    except Exception as e:
        return None


def check_brightness(frame):
    brightness = np.mean(frame)
    if brightness < BRIGHTNESS_THRESHOLD:
        return False
    return True


def detect_obstacles(model, frame, prev_max_area):
    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = model(img_rgb)
    df = results.pandas().xyxy[0]

    frame_center_x = frame.shape[1] / 2

    danger = False
    turn_direction = 'right'
    dead_end = False
    aeb_trigger = False
    current_max_area = 0

    if not df.empty:
        df = df.copy()
        df['area'] = (df['xmax'] - df['xmin']) * (df['ymax'] - df['ymin'])
        df = df.sort_values('area', ascending=False).reset_index(drop=True)

        for _, row in df.iterrows():
            x1, y1, x2, y2 = int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])
            label = row['name']
            conf = row['confidence']
            area = int(row['area'])

            if area > current_max_area:
                current_max_area = area

            # Draw bounding box and label
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"{label} {conf:.0%} A:{area}", (x1, y2 + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

            # Decide turn direction based on object position
            obj_center_x = (x1 + x2) / 2

            if obj_center_x < frame_center_x:
                turn_direction = 'right'
                cv2.putText(frame, f"TURN RIGHT ({label})", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            else:
                turn_direction = 'left'
                cv2.putText(frame, f"TURN LEFT ({label})", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

            # Classify threat level by area
            if area > DEAD_END_AREA_THRESHOLD:
                dead_end = True
                update_log(f"DEAD END: {label} area={area} > threshold={DEAD_END_AREA_THRESHOLD}")
                break
            elif area > DANGER_AREA_THRESHOLD:
                danger = True
                update_log(f"DANGER: {label} area={area} > threshold={DANGER_AREA_THRESHOLD} → {turn_direction}")
                break
            else:
                logger.debug(f"Object '{label}' area={area} < threshold={DANGER_AREA_THRESHOLD}, ignoring")

        # Show area info on the frame overlay
        cv2.putText(frame, f"MaxArea: {current_max_area} / Thresh: {DANGER_AREA_THRESHOLD}",
                    (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    area_expansion = current_max_area - prev_max_area
    if prev_max_area > 0 and area_expansion > TTC_EXPANSION_THRESHOLD:
        aeb_trigger = True
        cv2.putText(frame, "AEB: Emergency brake!", (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

    return danger, turn_direction, dead_end, aeb_trigger, current_max_area, frame


def ai_worker():
    global latest_frame
    
    # Try to load model — if it fails, run in passthrough mode (camera only, no AI)
    model = None
    try:
        model = load_model()
    except Exception as e:
        update_log(f"Model load failed: {e}")
        update_log("Running in PASSTHROUGH mode (camera only, no AI detection)")
    
    current_action = "stop"
    avoidance_timer = 0
    camera_fail_count = 0
    prev_max_area = 0
    needs_escape_turn = False

    send_command('stop')
    update_log("AI Worker thread started.")

    while True:
        try:
            frame = capture_frame()
            if frame is None:
                ai_state["camera_ok"] = False
                camera_fail_count += 1
                if camera_fail_count >= MAX_CAMERA_FAILURES:
                    if current_action != "stop":
                        update_log("Continuous camera failure! Stopping safely.")
                        send_command('stop')
                        current_action = "stop"
                        ai_state["current_action"] = current_action
                prev_max_area = 0
                time.sleep(1)
                continue

            camera_fail_count = 0
            ai_state["camera_ok"] = True

            # Safety layer 1: Camera blindness check
            if not check_brightness(frame):
                if current_action != "stop":
                    update_log("Image too dark! Emergency Stop.")
                    send_command('stop')
                    current_action = "stop"
                    ai_state["current_action"] = current_action
                prev_max_area = 0
                cv2.putText(frame, "CAMERA BLIND", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)
                with frame_lock:
                    latest_frame = frame
                time.sleep(0.1)
                continue

            # Safety layer 2: Ultrasonic sensor
            sonic_distance = 999.0
            if USE_ULTRASONIC:
                try:
                    resp_dist = requests.get(DISTANCE_URL, timeout=0.2)
                    sonic_distance = float(resp_dist.text)
                except Exception:
                    pass
            ai_state["distance"] = sonic_distance

            # === PASSTHROUGH MODE (no model loaded) ===
            # Show raw camera frame on Web GUI without AI analysis
            if model is None:
                cv2.putText(frame, "PASSTHROUGH - No AI Model", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
                with frame_lock:
                    latest_frame = frame
                time.sleep(0.05)
                continue

            # === NORMAL MODE (model loaded) ===
            # Analyze image
            danger, turn_direction, visual_dead_end, aeb_trigger, current_max_area, annotated_frame = detect_obstacles(model, frame, prev_max_area)
            prev_max_area = current_max_area

            # Fuse results
            is_dead_end = visual_dead_end or (sonic_distance < 10)
            is_danger = danger or (sonic_distance < 25)

            ai_state["danger"] = is_danger
            ai_state["dead_end"] = is_dead_end
            ai_state["aeb_triggered"] = aeb_trigger

            # Update latest frame for Web GUI
            with frame_lock:
                latest_frame = annotated_frame

            # Only control the car if AI is running
            if not ai_state["is_running"]:
                if current_action != "stop":
                    send_command("stop")
                    current_action = "stop"
                    ai_state["current_action"] = current_action
                    update_log("AI Stopped. Car halted.")
                else:
                    ai_state["current_action"] = "stop (paused)"
                time.sleep(0.1)
                continue

            # Control decision-making
            if time.time() >= avoidance_timer:
                if needs_escape_turn:
                    update_log(f"Escape turning ({turn_direction.upper()})...")
                    send_command(turn_direction)
                    avoidance_timer = time.time() + POST_DEADEND_TURN_DURATION
                    current_action = f"avoiding {turn_direction}"
                    needs_escape_turn = False

                elif aeb_trigger:
                    update_log("AEB TRIGGERED! Emergency braking...")
                    send_command('stop')
                    avoidance_timer = time.time() + 1.5
                    current_action = "stop (AEB)"

                elif is_dead_end:
                    update_log("DEAD END! Reversing...")
                    send_command('stop')
                    avoidance_timer = time.time() + 1.0
                    current_action = "backward"
                    needs_escape_turn = True

                elif is_danger:
                    update_log(f"OBSTACLE! Steering {turn_direction.upper()}")
                    send_command(turn_direction)
                    avoidance_timer = time.time() + TURN_DURATION
                    current_action = f"avoiding {turn_direction}"

                else:
                    if current_action != "go":
                        update_log("Clear path - Going straight")
                        send_command("go")
                        current_action = "go"
            
            ai_state["current_action"] = current_action

        except Exception as e:
            update_log(f"System error: {e}")
            time.sleep(1)


# === FLASK ROUTES ===

@app.route('/')
def index():
    return render_template('index.html', pi_ip=PI_IP, snapshot_url=SNAPSHOT_URL)

def generate_video():
    while True:
        with frame_lock:
            if latest_frame is not None:
                ret, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
                if ret:
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.05) # ~20 fps

@app.route('/video_feed')
def video_feed():
    return Response(generate_video(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def get_status():
    return jsonify(ai_state)

@app.route('/api/toggle_ai', methods=['POST'])
def toggle_ai():
    data = request.json
    if 'state' in data:
        ai_state['is_running'] = bool(data['state'])
        action = "STARTED" if ai_state['is_running'] else "STOPPED"
        update_log(f"User {action} the AI Controller.")
        return jsonify({"status": "success", "is_running": ai_state['is_running']})
    return jsonify({"status": "error"}), 400

@app.route('/api/emergency_stop', methods=['POST'])
def emergency_stop():
    ai_state['is_running'] = False
    send_command("stop")
    update_log("EMERGENCY STOP TRIGGERED BY USER!")
    return jsonify({"status": "success"})


if __name__ == '__main__':
    def signal_handler(sig, frame_signal):
        logger.info("Received exit signal!")
        send_command('stop')
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    # Start AI Thread
    t = threading.Thread(target=ai_worker, daemon=True)
    t.start()

    # Start Flask Web Server
    logger.info("="*50)
    logger.info("WEB GUI IS RUNNING")
    logger.info("Open http://127.0.0.1:8080 in your browser")
    logger.info("="*50)
    app.run(host='0.0.0.0', port=8080, threaded=True, use_reloader=False)