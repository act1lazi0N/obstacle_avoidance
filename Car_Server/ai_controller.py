# File: ai_controller.py
# Environment: Local Server / Cloud (runs on personal computer or server)
# Description: AI controller using YOLOv5 combined with Sensor Fusion (Ultrasonic)
#              to detect obstacles and control the Raspberry Pi car via HTTP API.
#              Also integrates Automatic Emergency Braking (AEB - TTC)
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
from dotenv import load_dotenv

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
DANGER_AREA_THRESHOLD = 15000
DEAD_END_AREA_THRESHOLD = 50000
BRIGHTNESS_THRESHOLD = 15
MAX_CAMERA_FAILURES = 5


USE_ULTRASONIC = False
TTC_EXPANSION_THRESHOLD = 8000


def load_model():
    logger.info("Loading YOLOv5 model from models/best.pt...")
    temp = pathlib.PosixPath
    try:
        pathlib.PosixPath = pathlib.WindowsPath
        model = torch.hub.load('ultralytics/yolov5', 'custom', path='models/best.pt', force_reload=True)
        model.conf = 0.6
    finally:
        pathlib.PosixPath = temp
    logger.info("Model loaded successfully!")
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
        logger.error(f"Failed to capture frame: {e}")
        return None


def check_brightness(frame):
    brightness = np.mean(frame)
    if brightness < BRIGHTNESS_THRESHOLD:
        logger.warning(f"Image too dark (brightness: {brightness:.1f}) - Emergency stop!")
        return False
    return True


def detect_obstacles(model, frame, prev_max_area):
    """
    Analyze image to detect obstacles. Returns danger status and avoidance direction.
    """
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
            x1 = int(row['xmin'])
            y1 = int(row['ymin'])
            x2 = int(row['xmax'])
            y2 = int(row['ymax'])
            label = row['name']
            conf = row['confidence']
            area = int(row['area'])

            if area > current_max_area:
                current_max_area = area

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"{label} {conf:.0%}", (x1, y2 + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            obj_center_x = (x1 + x2) / 2

            if obj_center_x < frame_center_x:
                turn_direction = 'right'
                cv2.putText(frame, f"TURN RIGHT ({label})", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            else:
                turn_direction = 'left'
                cv2.putText(frame, f"TURN LEFT ({label})", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

            if area > DEAD_END_AREA_THRESHOLD:
                dead_end = True
                break
            elif area > DANGER_AREA_THRESHOLD:
                danger = True
                break

    area_expansion = current_max_area - prev_max_area
    if prev_max_area > 0 and area_expansion > TTC_EXPANSION_THRESHOLD:
        aeb_trigger = True
        cv2.putText(frame, "AEB: Emergency brake!", (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

    return danger, turn_direction, dead_end, aeb_trigger, current_max_area, frame


def main():
    model = load_model()
    current_action = "stop"
    avoidance_timer = 0
    camera_fail_count = 0
    prev_max_area = 0
    needs_escape_turn = False

    def emergency_stop(sig, frame_signal):
        logger.info("Received emergency stop signal!")
        send_command('stop')
        cv2.destroyAllWindows()
        sys.exit(0)

    signal.signal(signal.SIGINT, emergency_stop)
    send_command('stop')
    logger.info("Starting main loop. Press 'q' to quit.")

    try:
        while True:
            frame = capture_frame()
            if frame is None:
                camera_fail_count += 1
                if camera_fail_count >= MAX_CAMERA_FAILURES:
                    logger.error("Continuous camera failure! Stopping safely.")
                    send_command('stop')
                    current_action = "stop"
                prev_max_area = 0
                time.sleep(1)
                cv2.waitKey(1)
                continue

            camera_fail_count = 0

            # Safety layer 1: Camera blindness check
            if not check_brightness(frame):
                if current_action != "stop":
                    send_command('stop')
                    current_action = "stop"
                prev_max_area = 0
                cv2.imshow("Car blind", frame)
                cv2.waitKey(1)
                continue

            # Safety layer 2: Ultrasonic sensor
            if USE_ULTRASONIC:
                try:
                    resp_dist = requests.get(DISTANCE_URL, timeout=0.2)
                    sonic_distance = float(resp_dist.text)
                except Exception:
                    sonic_distance = 999
            else:
                sonic_distance = 999

            # Analyze image
            danger, turn_direction, visual_dead_end, aeb_trigger, current_max_area, annotated_frame = detect_obstacles(model, frame, prev_max_area)
            prev_max_area = current_max_area

            # Fuse dead-end results (Ultrasonic < 10cm OR Image area > 50000 pixels)
            is_dead_end = visual_dead_end or (sonic_distance < 10)

            # Fuse danger results (Ultrasonic < 25cm OR YOLO detection)
            is_danger = danger or (sonic_distance < 25)

            # Control decision-making
            if time.time() >= avoidance_timer:
                if needs_escape_turn:
                    logger.info(f"Escape turning from dead-end ({turn_direction.upper()})...")
                    send_command(turn_direction)
                    avoidance_timer = time.time() + POST_DEADEND_TURN_DURATION
                    current_action = "avoiding"
                    needs_escape_turn = False

                elif aeb_trigger:
                    logger.warning("AEB TRIGGERED! MOVING OBSTACLE! Emergency braking...")
                    send_command('stop')
                    avoidance_timer = time.time() + 1.5
                    current_action = "stop"

                elif is_dead_end:
                    logger.warning("DEAD END! Reversing...")
                    send_command('backward')
                    avoidance_timer = time.time() + 1.0
                    current_action = "backward"
                    needs_escape_turn = True

                elif is_danger:
                    logger.info(f"OBSTACLE! Steering {turn_direction.upper()}")
                    send_command(turn_direction)
                    avoidance_timer = time.time() + TURN_DURATION
                    current_action = "avoiding"

                else:
                    if current_action != "go":
                        logger.info("Clear path - Going straight")
                        send_command("go")
                        current_action = "go"

            cv2.imshow("Car's Perspective", annotated_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except Exception as e:
        logger.critical(f"System error: {e}")
    finally:
        send_command('stop')
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()