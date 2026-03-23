# Tên file: ai_controller.py
# Môi trường: Local Server / Cloud (chạy trên máy tính cá nhân hoặc máy chủ)
# Mô tả: Bộ điều khiển AI sử dụng YOLOv5 để phát hiện vật cản từ camera
#         trên Raspberry Pi, sau đó gửi lệnh điều khiển (đi thẳng, rẽ trái/phải, dừng)
#         về Pi thông qua HTTP API.
# -----------------------------------------------------------------------

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

# === CẤU HÌNH LOGGING ===
# Tắt cảnh báo FutureWarning từ PyTorch/NumPy để console sạch hơn
warnings.filterwarnings("ignore", category=FutureWarning)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Thiết lập logging cho file này
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# === CẤU HÌNH KẾT NỐI ĐẾN RASPBERRY PI ===
# Địa chỉ IP của Raspberry Pi (hoặc mock server khi mô phỏng)
PI_IP = "127.0.0.1"
# URL lấy ảnh chụp nhanh từ camera trên Pi
SNAPSHOT_URL = f"http://{PI_IP}:5000/snapshot"
# URL gửi lệnh điều khiển đến Pi
CONTROL_URL = f"http://{PI_IP}:5000/control"


# === CẤU HÌNH THAM SỐ PHÁT HIỆN VÀ ĐIỀU KHIỂN ===
# Thời gian rẽ mỗi lần tránh vật cản (giây)
TURN_DURATION = 0.8
# Ngưỡng diện tích vật cản (pixel²) để coi là nguy hiểm
DANGER_AREA_THRESHOLD = 15000
# Ngưỡng độ sáng tối thiểu - ảnh quá tối sẽ dừng xe
BRIGHTNESS_THRESHOLD = 15
# Số lần mất kết nối camera liên tiếp trước khi dừng hẳn xe
MAX_CAMERA_FAILURES = 5
# Ngưỡng tâm ảnh để quyết định rẽ trái/phải (pixel)
FRAME_CENTER_X = 160


def load_model():
    """
    Tải model YOLOv5 custom từ file best.pt.
    Sử dụng pathlib patch để tương thích giữa Windows và Linux
    (model được train trên Linux nhưng chạy trên Windows).

    Returns:
        model: Model YOLOv5 đã được tải và cấu hình
    """
    logger.info("Đang tải model YOLOv5 từ models/best.pt...")

    # Lưu lại PosixPath gốc trước khi patch
    temp = pathlib.PosixPath
    # Patch: chuyển PosixPath thành WindowsPath để đọc file .pt trên Windows
    pathlib.PosixPath = pathlib.WindowsPath

    model = torch.hub.load(
        'ultralytics/yolov5', 'custom',
        path='models/best.pt', force_reload=True
    )
    # Ngưỡng độ tự tin: chỉ nhận diện vật cản khi >60% chắc chắn
    model.conf = 0.6

    # Khôi phục PosixPath gốc để không ảnh hưởng các thư viện khác
    pathlib.PosixPath = temp

    logger.info("Tải model thành công!")
    return model


def send_command(cmd):
    """
    Gửi lệnh điều khiển đến Raspberry Pi qua HTTP GET.

    Args:
        cmd (str): Lệnh điều khiển ('go', 'stop', 'left', 'right')

    Returns:
        bool: True nếu gửi thành công, False nếu thất bại
    """
    try:
        requests.get(CONTROL_URL, params={'cmd': cmd}, timeout=0.5)
        return True
    except requests.exceptions.ConnectionError:
        logger.error(f"Mất kết nối đến Pi khi gửi lệnh '{cmd}'!")
        return False
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout khi gửi lệnh '{cmd}' đến Pi.")
        return False
    except Exception as e:
        logger.error(f"Lỗi không xác định khi gửi lệnh '{cmd}': {e}")
        return False


def capture_frame():
    """
    Lấy ảnh chụp nhanh từ camera trên Raspberry Pi.

    Returns:
        frame (numpy.ndarray | None): Ảnh BGR từ camera, hoặc None nếu thất bại
    """
    try:
        resp = requests.get(SNAPSHOT_URL, timeout=1)
        # Chuyển bytes nhận được thành mảng numpy
        img_arr = np.array(bytearray(resp.content), dtype=np.uint8)
        # Giải mã ảnh JPEG thành ảnh BGR
        frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
        if frame is None:
            logger.warning("Nhận được dữ liệu nhưng không giải mã được ảnh.")
        return frame
    except requests.exceptions.ConnectionError:
        logger.error("Không thể kết nối đến camera trên Pi!")
        return None
    except requests.exceptions.Timeout:
        logger.warning("Timeout khi lấy ảnh từ camera.")
        return None
    except Exception as e:
        logger.error(f"Lỗi khi lấy ảnh từ camera: {e}")
        return None


def check_brightness(frame):
    """
    Kiểm tra độ sáng trung bình của ảnh.
    Nếu ảnh quá tối (camera bị che, trời tối, ...) → nguy hiểm.

    Args:
        frame (numpy.ndarray): Ảnh BGR cần kiểm tra

    Returns:
        bool: True nếu đủ sáng để xử lý, False nếu quá tối
    """
    brightness = np.mean(frame)
    if brightness < BRIGHTNESS_THRESHOLD:
        logger.warning(f"Ảnh quá tối (độ sáng: {brightness:.1f}) → Dừng khẩn cấp!")
        return False
    return True


def detect_obstacles(model, frame):
    """
    Phát hiện vật cản trong ảnh bằng YOLOv5.

    Args:
        model: Model YOLOv5
        frame (numpy.ndarray): Ảnh BGR từ camera

    Returns:
        tuple: (danger, turn_direction, annotated_frame)
            - danger (bool): True nếu có vật cản nguy hiểm
            - turn_direction (str): 'left' hoặc 'right'
            - annotated_frame: Ảnh đã vẽ bounding box
    """
    # Chuyển BGR → RGB vì YOLOv5 yêu cầu đầu vào RGB
    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = model(img_rgb)
    # Lấy kết quả dạng DataFrame với tọa độ bounding box
    df = results.pandas().xyxy[0]

    danger = False
    turn_direction = 'right'  # Mặc định rẽ phải nếu không xác định được

    # Duyệt qua từng vật cản được phát hiện
    for idx, row in df.iterrows():
        # Lấy tọa độ bounding box
        x1 = int(row['xmin'])
        y1 = int(row['ymin'])
        x2 = int(row['xmax'])
        y2 = int(row['ymax'])
        label = row['name']
        conf = row['confidence']

        # Tính diện tích bounding box (pixel²)
        area = (x2 - x1) * (y2 - y1)

        # Vẽ bounding box lên ảnh (màu xanh lá)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        # Hiển thị tên + độ tin cậy
        cv2.putText(frame, f"{label} {conf:.0%}", (x1, y2 + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # Kiểm tra vật cản có đủ lớn (gần) để coi là nguy hiểm không
        if area > DANGER_AREA_THRESHOLD:
            danger = True

            # Tính tọa độ X tâm vật cản để quyết định hướng rẽ
            obj_center_x = (x1 + x2) / 2

            if obj_center_x < FRAME_CENTER_X:
                # Vật cản nằm bên TRÁI ảnh → Rẽ PHẢI để tránh
                turn_direction = 'right'
                cv2.putText(frame, f"RE PHAI ({label})",
                            (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 255, 255), 2)
            else:
                # Vật cản nằm bên PHẢI ảnh → Rẽ TRÁI để tránh
                turn_direction = 'left'
                cv2.putText(frame, f"RE TRAI ({label})",
                            (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (255, 255, 0), 2)

            # Chỉ xử lý vật cản gần nhất (nguy hiểm nhất) rồi thoát
            break

    return danger, turn_direction, frame


def main():
    """
    Vòng lặp chính: liên tục lấy ảnh → phát hiện vật cản → gửi lệnh điều khiển.
    Bao gồm các cơ chế an toàn:
        - Dừng xe khi mất kết nối camera quá nhiều lần
        - Dừng xe khi ảnh quá tối (camera bị che)
        - Dừng xe khi thoát chương trình (Ctrl+C hoặc phím 'q')
    """
    # === TẢI MODEL ===
    model = load_model()

    # === BIẾN TRẠNG THÁI ===
    current_action = "go"       # Hành động hiện tại ('go', 'stop', 'avoiding')
    avoidance_timer = 0         # Thời điểm cho phép chuyển hành động tiếp theo
    camera_fail_count = 0       # Bộ đếm lỗi camera liên tiếp

    # === XỬ LÝ TÍN HIỆU DỪNG KHẨN CẤP (Ctrl+C) ===
    def emergency_stop(sig, frame_signal):
        """Callback khi nhận tín hiệu ngắt → dừng xe ngay lập tức."""
        logger.info("Nhận tín hiệu dừng khẩn cấp (Ctrl+C)!")
        send_command('stop')
        cv2.destroyAllWindows()
        sys.exit(0)

    signal.signal(signal.SIGINT, emergency_stop)

    logger.info("Bắt đầu vòng lặp điều khiển. Nhấn 'q' hoặc Ctrl+C để thoát.")

    try:
        while True:
            # --- BƯỚC 1: Lấy ảnh từ camera ---
            frame = capture_frame()

            if frame is None:
                camera_fail_count += 1
                logger.warning(
                    f"Mất kết nối camera ({camera_fail_count}/{MAX_CAMERA_FAILURES})"
                )

                # AN TOÀN: Nếu mất kết nối quá nhiều lần → dừng xe
                if camera_fail_count >= MAX_CAMERA_FAILURES:
                    logger.error(
                        "Mất kết nối camera liên tục! Dừng xe để đảm bảo an toàn."
                    )
                    send_command('stop')
                    current_action = "stop"

                time.sleep(1)
                continue

            # Reset bộ đếm lỗi khi nhận được ảnh thành công
            camera_fail_count = 0

            # --- BƯỚC 2: Kiểm tra độ sáng (lớp chống mù) ---
            if not check_brightness(frame):
                # Ảnh quá tối → dừng xe ngay lập tức
                if current_action != "stop":
                    send_command('stop')
                    current_action = "stop"

                cv2.imshow("Car blind", frame)
                cv2.waitKey(1)
                continue

            # --- BƯỚC 3: Phát hiện vật cản bằng YOLOv5 ---
            danger, turn_direction, annotated_frame = detect_obstacles(model, frame)

            # --- BƯỚC 4: Điều khiển xe dựa trên kết quả phân tích ---
            # Chỉ thay đổi hành động khi đã hết thời gian trễ (avoidance_timer)
            if time.time() >= avoidance_timer:
                if danger:
                    # Có vật cản nguy hiểm → rẽ tránh
                    logger.info(
                        f"Phát hiện vật cản! Rẽ {turn_direction.upper()} "
                        f"trong {TURN_DURATION}s"
                    )
                    send_command(turn_direction)

                    # Đặt khoảng trễ để xe hoàn thành thao tác rẽ
                    avoidance_timer = time.time() + TURN_DURATION
                    current_action = "avoiding"
                else:
                    # Không có vật cản → đi thẳng
                    if current_action != "go":
                        logger.info("Đường trống → Đi thẳng")
                        send_command("go")
                        current_action = "go"

            # --- BƯỚC 5: Hiển thị ảnh trên màn hình (debug) ---
            cv2.imshow("Car's Perspective", annotated_frame)

            # Nhấn 'q' để thoát vòng lặp
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logger.info("Người dùng nhấn 'q' → Thoát chương trình.")
                break

    except Exception as e:
        # AN TOÀN: Bắt mọi lỗi không mong muốn → luôn dừng xe
        logger.critical(f"Lỗi nghiêm trọng trong vòng lặp chính: {e}")
    finally:
        # LUÔN dừng xe và giải phóng tài nguyên khi thoát
        logger.info("Đang dừng xe và giải phóng tài nguyên...")
        send_command('stop')
        cv2.destroyAllWindows()
        logger.info("Đã thoát chương trình an toàn.")


# === ĐIỂM BẮT ĐẦU CHƯƠNG TRÌNH ===
if __name__ == '__main__':
    main()