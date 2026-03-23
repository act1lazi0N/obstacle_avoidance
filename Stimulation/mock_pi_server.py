# Tên file: mock_pi_server.py
# Môi trường: Máy tính cá nhân (Simulation / Mô phỏng)
# Mô tả: Server giả lập Raspberry Pi, dùng để kiểm thử logic AI trên
#         máy tính mà KHÔNG cần phần cứng thật (không cần Pi, motor, GPIO).
#         - Dùng webcam laptop thay cho PiCamera
#         - In lệnh motor ra console thay vì điều khiển GPIO thật
#         - Nếu không có webcam → tự tạo ảnh giả để test
# -----------------------------------------------------------------------

import time
import signal
import sys
import logging

import cv2
import numpy as np
from flask import Flask, Response, request

# === CẤU HÌNH LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Tắt log mặc định của Flask
werkzeug_log = logging.getLogger('werkzeug')
werkzeug_log.setLevel(logging.ERROR)

# === CẤU HÌNH ===
CAMERA_INDEX = 0  # Index webcam (0 = webcam mặc định)
CAMERA_WIDTH = 320  # Chiều rộng ảnh (pixel)
CAMERA_HEIGHT = 240  # Chiều cao ảnh (pixel)
JPEG_QUALITY = 50  # Chất lượng ảnh JPEG (0-100)
USE_MOCK_FRAME = False  # Cờ: True nếu không tìm thấy webcam, dùng ảnh giả


# === GIẢ LẬP MOTOR ===
# Các hàm này CHỈ in ra console, không điều khiển phần cứng thật
def go_forward():
    """Mô phỏng lệnh đi thẳng"""
    logger.info("[MOTOR] Đang đi THẲNG (Bánh Trái: TIẾN | Bánh Phải: TIẾN)")


def stop_car():
    """Mô phỏng lệnh dừng"""
    logger.info("[MOTOR] Đã DỪNG LẠI")


def turn_left():
    """Mô phỏng lệnh rẽ trái"""
    logger.info("[MOTOR] Rẽ TRÁI (Bánh Trái: LÙI | Bánh Phải: TIẾN)")


def turn_right():
    """Mô phỏng lệnh rẽ phải"""
    logger.info("[MOTOR] Rẽ PHẢI (Bánh Trái: TIẾN | Bánh Phải: LÙI)")

def go_backward():
    """Mô phỏng đi lùi"""
    print("🔙 [MOTOR] Đi LÙI (Bánh Trái: LÙI | Bánh Phải: LÙI)")


# === KHỞI TẠO CAMERA ===
def setup_camera():
    """
    Thử mở webcam. Nếu không có webcam (ví dụ: chạy trên server không
    có màn hình) → chuyển sang chế độ tạo ảnh giả (mock frame).

    Returns:
        cv2.VideoCapture | None: Đối tượng camera, hoặc None nếu dùng mock
    """
    global USE_MOCK_FRAME

    camera = cv2.VideoCapture(CAMERA_INDEX)

    if not camera.isOpened():
        logger.warning("=" * 50)
        logger.warning("Không tìm thấy webcam!")
        logger.warning("Chuyển sang chế độ MÔ PHỎNG ẢNH GIẢ")
        logger.warning("(Ảnh đen + text, đủ để test logic AI)")
        logger.warning("=" * 50)
        USE_MOCK_FRAME = True
        return None

    # Đặt độ phân giải webcam
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    logger.info(f"Webcam đã sẵn sàng ({CAMERA_WIDTH}x{CAMERA_HEIGHT})")
    return camera


def generate_mock_frame():
    """
    Tạo ảnh giả khi không có webcam.
    Ảnh bao gồm: nền gradient xám + text thông báo + timestamp.
    Đủ sáng để AI server không kích hoạt chế độ 'ảnh quá tối'.

    Returns:
        numpy.ndarray: Ảnh BGR 320x240
    """
    # Tạo nền gradient xám (từ tối đến sáng) để có độ sáng trung bình đủ cao
    frame = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
    for y in range(CAMERA_HEIGHT):
        brightness = int(80 + (y / CAMERA_HEIGHT) * 100)  # 80-180
        frame[y, :] = [brightness, brightness, brightness]

    # Thêm text thông báo
    cv2.putText(
        frame, "MOCK CAMERA", (60, 100),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
    )
    cv2.putText(
        frame, "No webcam detected", (50, 140),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1
    )

    # Thêm timestamp để xác nhận ảnh đang được cập nhật
    timestamp = time.strftime("%H:%M:%S")
    cv2.putText(
        frame, timestamp, (110, 200),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2
    )

    return frame


def read_frame(camera):
    """
    Đọc 1 frame từ webcam hoặc tạo frame giả.

    Args:
        camera: Đối tượng cv2.VideoCapture hoặc None

    Returns:
        tuple: (success: bool, frame: numpy.ndarray)
    """
    if USE_MOCK_FRAME or camera is None:
        return True, generate_mock_frame()

    try:
        success, frame = camera.read()
        if not success:
            logger.warning("Webcam trả về frame rỗng, dùng mock frame thay thế.")
            return True, generate_mock_frame()
        return True, frame
    except Exception as e:
        logger.error(f"Lỗi đọc webcam: {e}")
        return True, generate_mock_frame()


# === TẠO ỨNG DỤNG FLASK ===
app = Flask(__name__)

# Biến toàn cục cho camera
camera = None


@app.route('/video_feed')
def video_feed():
    """
    Streaming video MJPEG qua HTTP (dùng để xem trực tiếp trên trình duyệt).
    Truy cập: http://127.0.0.1:5000/video_feed
    """

    def generate_frames():
        """Generator: liên tục đọc frame và gửi dưới dạng MJPEG stream."""
        while True:
            success, frame = read_frame(camera)
            if not success:
                break

            ret, buffer = cv2.imencode(
                '.jpg', frame,
                [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
            )
            if ret:
                yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n'
                        + buffer.tobytes()
                        + b'\r\n'
                )

    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/control', methods=['GET'])
def control():
    """
    API giả lập điều khiển motor.
    Nhận lệnh qua tham số ?cmd=go|stop|left|right
    Chỉ in ra console, không điều khiển phần cứng.
    """
    cmd = request.args.get('cmd', '').lower()

    if cmd == 'go':
        go_forward()
    elif cmd == 'stop':
        stop_car()
    elif cmd == 'left':
        turn_left()
    elif cmd == 'right':
        turn_right()
    elif cmd == 'backward':
        go_backward()
    else:
        logger.warning(f"Nhận lệnh không hợp lệ: '{cmd}'")
        return f"Lệnh không hợp lệ: {cmd}", 400

    return "OK"


@app.route('/snapshot')
def snapshot():
    """
    Chụp ảnh nhanh (dùng cho AI server lấy ảnh phân tích).
    Trả về 1 ảnh JPEG duy nhất.
    - Nếu có webcam → chụp từ webcam
    - Nếu không có webcam → trả về ảnh giả
    """
    success, frame = read_frame(camera)

    if success and frame is not None:
        ret, buffer = cv2.imencode(
            '.jpg', frame,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        if ret:
            return Response(buffer.tobytes(), mimetype='image/jpeg')

    logger.error("Không thể tạo ảnh snapshot!")
    return "Lỗi Camera", 500

# --- GIẢ LẬP CẢM BIẾN SIÊU ÂM ---
@app.route('/distance')
def get_distance():

    fake_distance = 100
    return str(fake_distance)


@app.route('/')
def index():
    """Trang chủ hiển thị trạng thái mock server."""
    mode = "Webcam" if not USE_MOCK_FRAME else " Ảnh giả (Mock)"
    return (
        "<h1>Mock Pi Server (Mô phỏng)</h1>"
        f"<p>Chế độ camera: {mode}</p>"
        "<p>API endpoints:</p>"
        "<ul>"
        "<li><a href='/snapshot'>/snapshot</a> - Chụp ảnh</li>"
        "<li><a href='/video_feed'>/video_feed</a> - Xem video</li>"
        "<li>/control?cmd=go|stop|left|right - Điều khiển (giả lập)</li>"
        "</ul>"
    )


def cleanup(sig=None, frame=None):
    """
    Dọn dẹp tài nguyên khi tắt chương trình.
    Giải phóng webcam để các chương trình khác có thể sử dụng.
    """
    logger.info("Đang dọn dẹp tài nguyên...")

    if camera is not None:
        try:
            camera.release()
            logger.info("Đã giải phóng webcam.")
        except Exception as e:
            logger.warning(f"Lỗi khi giải phóng webcam: {e}")

    logger.info("Đã thoát mock server.")
    sys.exit(0)


# === ĐIỂM BẮT ĐẦU CHƯƠNG TRÌNH ===
def main():
    """Khởi tạo camera mô phỏng và chạy Flask server."""
    global camera

    # Đăng ký signal handler để dọn dẹp khi Ctrl+C
    signal.signal(signal.SIGINT, cleanup)

    # Khởi tạo webcam (hoặc chuyển sang mock nếu không có)
    camera = setup_camera()

    # Hiển thị thông tin server
    logger.info("=" * 50)
    logger.info("MOCK PI SERVER ĐANG CHẠY (Mô phỏng)")
    logger.info("Địa chỉ: http://127.0.0.1:5000")
    logger.info("Chế độ: " + ("Webcam" if not USE_MOCK_FRAME else "Ảnh giả"))
    logger.info("Đợi lệnh từ AI Server...")
    logger.info("Nhấn Ctrl+C để dừng")
    logger.info("=" * 50)

    # Chạy Flask server trên localhost
    app.run(host='127.0.0.1', port=5000, threaded=True)


if __name__ == '__main__':
    main()
