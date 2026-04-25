# Tên file: ai_controller.py
# Môi trường: Local Server / Cloud (chạy trên máy tính cá nhân hoặc máy chủ)
# Mô tả: Bộ điều khiển AI sử dụng YOLOv5 kết hợp Sensor Fusion (Siêu âm) để
#        phát hiện vật cản và điều khiển xe Raspberry Pi qua HTTP API. Thêm nữa
#        tích hợp thêm Phanh khẩn cấp động học (AEB - TTC)
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

load_dotenv() #Từ giờ chỉ sửa bên .env

# Nếu trong file .env không có biến CAR_IP, nó sẽ mặc định lấy "127.0.0.1" để test
PI_IP = os.getenv("CAR_IP", "127.0.0.1")
SNAPSHOT_URL = f"http://{PI_IP}:5000/snapshot"
CONTROL_URL = f"http://{PI_IP}:5000/control"
DISTANCE_URL = f"http://{PI_IP}:5000/distance"

TURN_DURATION = 0.8
DANGER_AREA_THRESHOLD = 15000
DEAD_END_AREA_THRESHOLD = 50000
BRIGHTNESS_THRESHOLD = 15
MAX_CAMERA_FAILURES = 5
FRAME_CENTER_X = 160

USE_ULTRASONIC = False
# Ngưỡng phanh khẩn cấp
TTC_EXPANSION_THRESHOLD = 8000


def load_model():
    logger.info("Đang tải model YOLOv5 từ models/best.pt...")
    temp = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath
    model = torch.hub.load('ultralytics/yolov5', 'custom', path='models/best.pt', force_reload=True)
    model.conf = 0.6
    pathlib.PosixPath = temp
    logger.info("Tải model thành công!")
    return model


def send_command(cmd):
    try:
        requests.get(CONTROL_URL, params={'cmd': cmd}, timeout=0.5)
        return True
    except requests.exceptions.ConnectionError:
        logger.error(f"Mất kết nối đến Pi khi gửi lệnh '{cmd}'!")
        return False
    except Exception as e:
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
        logger.warning(f"Ảnh quá tối (độ sáng: {brightness:.1f}) → Dừng khẩn cấp!")
        return False
    return True


def detect_obstacles(model, frame, prev_max_area):
    """
    Phân tích hình ảnh để tìm vật cản. Trả về trạng thái nguy hiểm và hướng xử lý.
    """
    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = model(img_rgb)
    df = results.pandas().xyxy[0]

    danger = False
    turn_direction = 'right'
    dead_end = False
    aeb_trigger = False
    current_max_area = 0

    for idx, row in df.iterrows():
        x1, y1, x2, y2 = int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])
        label = row['name']
        conf = row['confidence']
        area = (x2 - x1) * (y2 - y1)

        if area > current_max_area:
            current_max_area = area

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"{label} {conf:.0%}", (x1, y2 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        obj_center_x = (x1 + x2) / 2

        if obj_center_x < FRAME_CENTER_X:
            turn_direction = 'right'
            cv2.putText(frame, f"RE PHAI ({label})", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        else:
            turn_direction = 'left'
            cv2.putText(frame, f"RE TRAI ({label})", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        if area > DEAD_END_AREA_THRESHOLD:
            dead_end = True
            break
        elif area > DANGER_AREA_THRESHOLD:
            danger = True
            break

    if current_max_area - prev_max_area > TTC_EXPANSION_THRESHOLD:
        aeb_trigger = True
        cv2.putText(frame, "AEB: Emergency brake!", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

    return danger, turn_direction, dead_end, aeb_trigger, current_max_area, frame


def main():
    model = load_model()
    current_action = "go"
    avoidance_timer = 0
    camera_fail_count = 0
    prev_max_area = 0

    def emergency_stop(sig, frame_signal):
        logger.info("Nhận tín hiệu dừng khẩn cấp!")
        send_command('stop')
        cv2.destroyAllWindows()
        sys.exit(0)

    signal.signal(signal.SIGINT, emergency_stop)
    logger.info("Bắt đầu vòng lặp. Nhấn 'q' để thoát.")

    try:
        while True:
            frame = capture_frame()
            if frame is None:
                camera_fail_count += 1
                if camera_fail_count >= MAX_CAMERA_FAILURES:
                    logger.error("Mất camera liên tục! Dừng an toàn.")
                    send_command('stop')
                    current_action = "stop"
                time.sleep(1)
                cv2.waitKey(1)
                continue

            camera_fail_count = 0

            # Lớp bảo vệ 1: Mù camera
            if not check_brightness(frame):
                if current_action != "stop":
                    send_command('stop')
                    current_action = "stop"
                cv2.imshow("Car blind", frame)
                cv2.waitKey(1)
                continue

            # Lớp bảo vệ 2: Cảm biến siêu âm
            if USE_ULTRASONIC:
                try:
                    resp_dist = requests.get(DISTANCE_URL, timeout=0.2)
                    sonic_distance = float(resp_dist.text)
                except:
                    sonic_distance = 999
            else:
                sonic_distance = 999

            # Phân tích hình ảnh
            danger, turn_direction, visual_dead_end, aeb_trigger, current_max_area, annotated_frame = detect_obstacles(model, frame, prev_max_area)
            prev_max_area = current_max_area

            # Dung hợp kết quả Ngõ cụt (Siêu âm < 10cm HOẶC Ảnh chiếm > 50000 pixels)
            is_dead_end = visual_dead_end or (sonic_distance < 10)

            # Dung hợp kết quả Nguy hiểm (Siêu âm < 25cm HOẶC YOLO phát hiện)
            is_danger = danger or (sonic_distance < 25)

            # Ra quyết định điều khiển
            if time.time() >= avoidance_timer:
                if aeb_trigger:
                    logger.warning("AEB KÍCH HOẠT! VẬT CẢN ĐỘNG! Phanh gấp...")
                    send_command('stop')
                    avoidance_timer = time.time() + 1.5  # Khóa phanh khẩn cấp trong 1.5s
                    current_action = "stop"
                elif is_dead_end:
                    logger.warning("NGÕ CỤT! Đang cài số lùi...")
                    send_command('backward')
                    avoidance_timer = time.time() + 1.0
                    current_action = "backward"
                elif is_danger:
                    logger.info(f"VẬT CẢN! Bẻ lái sang {turn_direction.upper()}")
                    send_command(turn_direction)
                    avoidance_timer = time.time() + TURN_DURATION
                    current_action = "avoiding"
                else:
                    if current_action != "go":
                        logger.info("Đường trống → Đi thẳng")
                        send_command("go")
                        current_action = "go"

            cv2.imshow("Car's Perspective", annotated_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except Exception as e:
        logger.critical(f"Lỗi hệ thống: {e}")
    finally:
        send_command('stop')
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()