# File: collect_data.py
# Description: Auto-capture tool for taking images from Raspberry Pi camera to build YOLO training dataset
# -----------------------------------------------------------------------

import cv2
import requests
import numpy as np
import time
import os

from dotenv import load_dotenv

load_dotenv()

# If CAR_IP is not set in .env, default to "127.0.0.1" for local testing
PI_IP = os.getenv("CAR_IP", "127.0.0.1")
SNAPSHOT_URL = f"http://{PI_IP}:5000/snapshot"

SAVE_DIR = "dataset_images"
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

DELAY_BETWEEN_SHOTS = 1.0


def main():
    print(f"Starting data collection from {SNAPSHOT_URL}...")
    print(f"Images will be saved to: {SAVE_DIR}/")
    print("Press 'q' on the image window to STOP capturing.")

    count = 1
    while True:
        try:
            resp = requests.get(SNAPSHOT_URL, timeout=2.0)
            img_arr = np.array(bytearray(resp.content), dtype=np.uint8)
            frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

            if frame is not None:
                filename = os.path.join(SAVE_DIR, f"image_{count:03d}.jpg")
                cv2.imwrite(filename, frame)
                print(f"[+] Saved: {filename}")
                count += 1
                cv2.imshow("Data Collection", frame)
            else:
                print("[-] No frame received.")

        except Exception as e:
            print(f"[-] Connection error: {e}")

        if cv2.waitKey(int(DELAY_BETWEEN_SHOTS * 1000)) & 0xFF == ord('q'):
            print("Data collection stopped!")
            break
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()