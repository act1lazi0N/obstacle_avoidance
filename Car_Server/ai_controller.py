import time
import cv2
import requests
import torch.hub
import pathlib

PI_IP = "127.0.0.1"
VIDEO_URL = f"http://{PI_IP}:5000/video_feed"
CONTROL_URL = f"http://{PI_IP}:5000/control"

# Tải model
print("Installing model from best.pt")

temp = pathlib.PosixPath
pathlib.PosixPath = pathlib.WindowsPath
model = torch.hub.load('ultralytics/yolov5', 'custom', path='models/best.pt', force_reload=True)
model.conf = 0.6 # Độ tự tin: 60% chắc chắn là vật cản
pathlib.PosixPath = temp


def send(cmd):
    try:
        requests.get(CONTROL_URL, params={"cmd": cmd}, timeout=0.1)
    except:
        pass

print("Connecting with Camera...")
cap = cv2.VideoCapture(VIDEO_URL)

current_action = "go"
avoidance_timer = 0
# Vòng lặp suy nghĩ
while True:
    ret, frame = cap.read()
    if not ret:
        print("Camera not connected")
        time.sleep(1)
        continue

    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = model(img_rgb)
    df = results.pandas().xyxy[0]

    danger = False

    for index, row in df.iterrows():
        x1, y1, x2, y2 = int(row['xmin']), int(row['ymin']), int(row['xmax']), int(row['ymax'])
        label = row['name']
        conf = row['confidence']

        # Diện tích vật cản
        area = (x2 - x1) * (y2 - y1)

        # Khung bao quanh vật cản
        cv2.rectangle(frame, (x1, y1), (x2, y2), color=(0, 0, 255), thickness=2)
        cv2.putText(frame, f"{label} {conf:.2f}", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        if area > 15000:
            danger = True
            break

    if time.time() < avoidance_timer:
        pass
    else:
        if danger:
            print("Danger")
            send('right')
            avoidance_timer = time.time() + 0.5
            current_action = "avoiding"
        else:
            if current_action != "go":
                print("Go straight")
                send('go')
                current_action = "go"

    cv2.imshow("AI Controller View", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        send('stop')
        break

cap.release()
cv2.destroyAllWindows()

