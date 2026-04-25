# Tên file: collect_data.py
# Mô tả: Tool tự động chụp ảnh từ Camera của Raspberry Pi để làm Dataset train YOLO
# -----------------------------------------------------------------------

import cv2
import requests
import numpy as np
import time
import os

from dotenv import load_dotenv

load_dotenv()

# Nếu trong file .env không có biến CAR_IP, nó sẽ mặc định lấy "127.0.0.1" để test
PI_IP = os.getenv("CAR_IP", "127.0.0.1")
SNAPSHOT_URL = f"http://{PI_IP}:5000/snapshot"

SAVE_DIR = "dataset_images"
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

DELAY_BETWEEN_SHOTS = 1.0


def main():
    print(f"Bắt đầu thu thập dữ liệu từ {SNAPSHOT_URL}...")
    print(f"Ảnh sẽ được lưu vào thư mục: {SAVE_DIR}/")
    print("Nhấn 'q' trên cửa sổ hình ảnh để DỪNG chụp.")

    count = 1
    while True:
        try:
            resp = requests.get(SNAPSHOT_URL, timeout=2.0)
            img_arr = np.array(bytearray(resp.content), dtype=np.uint8)
            frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

            if frame is not None:
                filename = os.path.join(SAVE_DIR, f"image_{count:03d}.jpg")
                cv2.imwrite(filename, frame)
                print(f"[+] Đã lưu: {filename}")
                count += 1
                cv2.imshow("Data Collection", frame)
            else:
                print("[-] Không nhận được khung hình.")

        except Exception as e:
            print(f"[-] Lỗi kết nối: {e}")

        if cv2.waitKey(int(DELAY_BETWEEN_SHOTS * 1000)) & 0xFF == ord('q'):
            print("Đã dừng thu thập dữ liệu!")
            break
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()