import time
import warnings

import cv2
import requests
import torch.hub
import pathlib
import logging

import numpy as np

# Tắt tính năng default
warnings.filterwarnings("ignore", category=FutureWarning)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

PI_IP = "127.0.0.1"
SNAPSHOT_URL = f"http://{PI_IP}:5000/snapshot"
CONTROL_URL = f"http://{PI_IP}:5000/control"

# Tải model
print("Installing model from best.pt")

temp = pathlib.PosixPath
pathlib.PosixPath = pathlib.WindowsPath
model = torch.hub.load('ultralytics/yolov5', 'custom', path='models/best.pt', force_reload=True)
model.conf = 0.6 # Độ tự tin: 60% chắc chắn là vật cản
pathlib.PosixPath = temp
TURN_DURATION = 0.8

current_action = "go"
avoidance_timer = 0

def send(cmd):
    try:
        requests.get(CONTROL_URL, params={'cmd': cmd}, timeout=0.1)
    except:
        pass

# Triển khai suy luận
while True:

    # Kiểm tra camera
    try:
        resp = requests.get(SNAPSHOT_URL, timeout=1)
        img_arr = np.array(bytearray(resp.content), dtype=np.uint8)
        frame = cv2.imdecode(img_arr, -1)
    except:
        print("Camera not available")
        time.sleep(1)
        continue

    # Lớp chống mù
    brightness = np.mean(frame)
    if (brightness < 15):
        print(f"Brightness too low (Brightness: {brightness:.1}) Emergency stop!")
        if current_action != "stop":
            send('stop')
            current_action = "stop"

        cv2.imshow("Car blind", frame)
        cv2.waitKey(1)
        continue


    # Lấy ảnh cho bộ xử lý
    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = model(img_rgb)
    df = results.pandas().xyxy[0]

    danger = False
    turn_direction = 'right'

    # Phân tích vật cản
    """
    Chỉ dùng để phân tích các số liệu nhằm phần tích 
    vật cản và độ trễ nhằm di chuyển xe một cách linh hoạt
    """
    for idx, row in df.iterrows():
        x1, y1, x2, y2 = int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])
        label = row['name']
        conf = row['confidence']
        area = (x2 - x1) * (y2 - y1)

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        if area > 15000:
            danger = True

            # Tính toán điểm tâm vật cản
            obj_center_x = (x1 + x2) / 2

            if obj_center_x < 160:
                # Vật bên trái -> Rẽ phải
                turn_direction = 'right'
                cv2.putText(frame, f"RE PHAI ({label})", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            else:
                # Vật bên phải -> Rẽ trái
                turn_direction = 'left'
                cv2.putText(frame, f"RE TRAI ({label})", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            break

    # Thực hiện điều khiển xe
    """
    Điều khiển xe sau khi đã hoàn tất xử lý ảnh
    """
    if time.time() >= avoidance_timer:
        if danger:
            print(f"Detected avoidance! Turn {turn_direction.upper()} in {TURN_DURATION} seconds" )
            send(turn_direction)

            # Khoẳng trễ
            avoidance_timer = time.time() + TURN_DURATION
            current_action = "avoiding"

        else:
            if current_action != "go":
                print("Go straight")
                send("go")
                current_action = "go"

    cv2.imshow("Car's Perspective", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        send('stop')
        break

cv2.destroyAllWindows()