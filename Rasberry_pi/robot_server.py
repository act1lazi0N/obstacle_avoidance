# Tên file: robot_server.py
# Môi trường: Edge Device (Raspberry Pi)
# Mô tả: Flask server chạy trực tiếp trên Raspberry Pi, cung cấp:
#         - API điều khiển motor (đi thẳng, rẽ trái/phải, dừng)
#         - API chụp ảnh từ PiCamera (snapshot / video feed)
#         - Graceful shutdown: tự cleanup GPIO khi tắt chương trình
# -----------------------------------------------------------------------

import time
import signal
import sys
import threading
import logging

from flask import Flask, Response, request

# === THỬ IMPORT THƯ VIỆN PHẦN CỨNG ===
# Nếu không chạy trên Raspberry Pi → báo lỗi rõ ràng
try:
    import RPi.GPIO as GPIO
except ImportError:
    print("=" * 60)
    print("LỖI: Không tìm thấy thư viện RPi.GPIO!")
    print("File này chỉ chạy được trên Raspberry Pi.")
    print("Nếu muốn test trên máy tính, hãy dùng:")
    print("  python Stimulation/mock_pi_server.py")
    print("=" * 60)
    sys.exit(1)

try:
    from picamera2 import Picamera2
except ImportError:
    print("=" * 60)
    print("LỖI: Không tìm thấy thư viện picamera2!")
    print("Cài đặt: sudo apt install -y python3-picamera2")
    print("=" * 60)
    sys.exit(1)


# === CẤU HÌNH LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Tắt log mặc định của Flask để console dễ đọc hơn
werkzeug_log = logging.getLogger('werkzeug')
werkzeug_log.setLevel(logging.ERROR)


# === CẤU HÌNH CHÂN GPIO CHO MOTOR (Driver L298N) ===
# Motor trái
MOTOR_LEFT_EN = 25      # Chân Enable motor trái (PWM)
MOTOR_LEFT_IN1 = 24     # Chân điều khiển chiều quay 1
MOTOR_LEFT_IN2 = 23     # Chân điều khiển chiều quay 2

# Motor phải
MOTOR_RIGHT_EN = 17     # Chân Enable motor phải (PWM)
MOTOR_RIGHT_IN1 = 27    # Chân điều khiển chiều quay 1
MOTOR_RIGHT_IN2 = 22    # Chân điều khiển chiều quay 2

# Tốc độ PWM mặc định (0-100)
DEFAULT_SPEED = 70

# Thời gian watchdog: nếu không nhận lệnh mới trong N giây → dừng xe
WATCHDOG_TIMEOUT = 3.0


# === CẤU HÌNH CAMERA ===
CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240
JPEG_QUALITY = 50       # Chất lượng ảnh JPEG (0-100), thấp = nhẹ hơn


# === KHỞI TẠO GPIO ===
def setup_gpio():
    """
    Thiết lập các chân GPIO cho 2 motor.
    Sử dụng chế độ BCM (đánh số theo tên GPIO, không theo vị trí vật lý).

    Returns:
        tuple: (pwm_left, pwm_right) - Hai đối tượng PWM để điều khiển tốc độ
    """
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Cấu hình chân OUTPUT cho motor trái
    GPIO.setup(MOTOR_LEFT_EN, GPIO.OUT)
    GPIO.setup(MOTOR_LEFT_IN1, GPIO.OUT)
    GPIO.setup(MOTOR_LEFT_IN2, GPIO.OUT)

    # Cấu hình chân OUTPUT cho motor phải
    GPIO.setup(MOTOR_RIGHT_EN, GPIO.OUT)
    GPIO.setup(MOTOR_RIGHT_IN1, GPIO.OUT)
    GPIO.setup(MOTOR_RIGHT_IN2, GPIO.OUT)

    # Khởi tạo PWM trên chân Enable để điều khiển tốc độ (tần số 1000Hz)
    pwm_left = GPIO.PWM(MOTOR_LEFT_EN, 1000)
    pwm_right = GPIO.PWM(MOTOR_RIGHT_EN, 1000)

    # Bắt đầu PWM với duty cycle = 0 (dừng)
    pwm_left.start(0)
    pwm_right.start(0)

    logger.info("Đã khởi tạo GPIO cho 2 motor.")
    return pwm_left, pwm_right


# === HÀM ĐIỀU KHIỂN MOTOR ===
def go_forward(pwm_left, pwm_right):
    """Đi thẳng: cả 2 motor quay tiến."""
    # Motor trái: TIẾN
    GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    # Motor phải: TIẾN
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
    # Đặt tốc độ
    pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
    pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Đang đi THẲNG")


def stop_car(pwm_left, pwm_right):
    """Dừng xe: tắt cả 2 motor."""
    GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
    pwm_left.ChangeDutyCycle(0)
    pwm_right.ChangeDutyCycle(0)
    logger.info("[MOTOR] Đã DỪNG")


def turn_left(pwm_left, pwm_right):
    """Rẽ trái: motor trái LÙI, motor phải TIẾN."""
    GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.HIGH)  # Motor trái: LÙI
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)  # Motor phải: TIẾN
    pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
    pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Rẽ TRÁI")


def turn_right(pwm_left, pwm_right):
    """Rẽ phải: motor trái TIẾN, motor phải LÙI."""
    GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)   # Motor trái: TIẾN
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH) # Motor phải: LÙI
    pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
    pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Rẽ PHẢI")


# === KHỞI TẠO CAMERA ===
def setup_camera():
    """
    Khởi tạo PiCamera2 với độ phân giải thấp để giảm độ trễ.

    Returns:
        Picamera2: Đối tượng camera đã được cấu hình và khởi động
    """
    try:
        camera = Picamera2()
        # Cấu hình preview với độ phân giải nhỏ để truyền nhanh qua mạng
        config = camera.create_preview_configuration(
            main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"}
        )
        camera.configure(config)
        camera.start()
        # Đợi camera ổn định (auto-exposure, auto-white-balance)
        time.sleep(2)
        logger.info(f"Camera PiCamera2 đã sẵn sàng ({CAMERA_WIDTH}x{CAMERA_HEIGHT})")
        return camera
    except Exception as e:
        logger.error(f"Không thể khởi tạo camera: {e}")
        raise


# === WATCHDOG TIMER ===
# Tự động dừng motor nếu server AI mất kết nối (không gửi lệnh mới)
last_command_time = time.time()


def watchdog_thread(pwm_left, pwm_right):
    """
    Luồng chạy nền: liên tục kiểm tra thời gian từ lệnh cuối cùng.
    Nếu quá WATCHDOG_TIMEOUT giây không nhận lệnh mới → dừng xe.
    Đây là cơ chế AN TOÀN quan trọng nhất khi mất kết nối mạng.
    """
    global last_command_time
    was_stopped = False

    while True:
        elapsed = time.time() - last_command_time
        if elapsed > WATCHDOG_TIMEOUT:
            if not was_stopped:
                logger.warning(
                    f"WATCHDOG: Không nhận lệnh trong {WATCHDOG_TIMEOUT}s → Dừng xe!"
                )
                stop_car(pwm_left, pwm_right)
                was_stopped = True
        else:
            was_stopped = False

        time.sleep(0.5)


# === TẠO ỨNG DỤNG FLASK ===
app = Flask(__name__)

# Biến toàn cục cho GPIO và camera (được khởi tạo trong main)
pwm_left = None
pwm_right = None
camera = None


@app.route('/control', methods=['GET'])
def control():
    """
    API điều khiển motor.
    Gửi GET request với tham số ?cmd=go|stop|left|right

    Returns:
        str: Thông báo kết quả
    """
    global last_command_time

    cmd = request.args.get('cmd', '').lower()

    # Cập nhật thời gian nhận lệnh cuối cho watchdog
    last_command_time = time.time()

    # Thực hiện lệnh điều khiển tương ứng
    if cmd == 'go':
        go_forward(pwm_left, pwm_right)
    elif cmd == 'stop':
        stop_car(pwm_left, pwm_right)
    elif cmd == 'left':
        turn_left(pwm_left, pwm_right)
    elif cmd == 'right':
        turn_right(pwm_left, pwm_right)
    else:
        logger.warning(f"Nhận lệnh không hợp lệ: '{cmd}'")
        return f"Lệnh không hợp lệ: {cmd}", 400

    return "OK"


@app.route('/snapshot')
def snapshot():
    """
    Chụp ảnh nhanh từ PiCamera.
    Trả về 1 ảnh JPEG duy nhất (dùng cho AI server lấy ảnh phân tích).
    Dùng snapshot thay vì video feed để giảm độ trễ.
    """
    try:
        import cv2
        # Chụp ảnh từ PiCamera2 (trả về numpy array RGB)
        frame = camera.capture_array()
        # Chuyển RGB → BGR cho OpenCV encode
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        # Nén thành JPEG
        ret, buffer = cv2.imencode(
            '.jpg', frame_bgr,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        if ret:
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        else:
            logger.error("Không thể encode ảnh JPEG!")
            return "Lỗi encode ảnh", 500
    except Exception as e:
        logger.error(f"Lỗi khi chụp ảnh: {e}")
        return f"Lỗi Camera: {e}", 500


@app.route('/video_feed')
def video_feed():
    """
    Streaming video MJPEG từ PiCamera (dùng để xem trực tiếp trên trình duyệt).
    Truy cập http://<PI_IP>:5000/video_feed để xem.
    """
    def generate_frames():
        """Generator: liên tục chụp ảnh và gửi dưới dạng MJPEG stream."""
        import cv2
        while True:
            try:
                frame = camera.capture_array()
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                ret, buffer = cv2.imencode(
                    '.jpg', frame_bgr,
                    [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                )
                if ret:
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n'
                        + buffer.tobytes()
                        + b'\r\n'
                    )
            except Exception as e:
                logger.error(f"Lỗi trong video stream: {e}")
                break

    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/')
def index():
    """Trang chủ hiển thị trạng thái server."""
    return (
        "<h1>🚗 Robot Server (Raspberry Pi)</h1>"
        "<p>API endpoints:</p>"
        "<ul>"
        "<li><a href='/snapshot'>/snapshot</a> - Chụp ảnh</li>"
        "<li><a href='/video_feed'>/video_feed</a> - Xem video</li>"
        "<li>/control?cmd=go|stop|left|right - Điều khiển</li>"
        "</ul>"
    )


def cleanup(sig=None, frame=None):
    """
    Dọn dẹp tài nguyên khi tắt chương trình.
    Được gọi khi nhận tín hiệu SIGINT (Ctrl+C) hoặc SIGTERM.
    AN TOÀN: Luôn dừng motor và giải phóng GPIO trước khi thoát.
    """
    logger.info("Đang dọn dẹp tài nguyên...")

    # Dừng motor trước tiên (QUAN TRỌNG NHẤT)
    if pwm_left and pwm_right:
        stop_car(pwm_left, pwm_right)

    # Tắt camera
    if camera:
        try:
            camera.stop()
            logger.info("Đã tắt camera.")
        except Exception as e:
            logger.warning(f"Lỗi khi tắt camera: {e}")

    # Giải phóng GPIO
    GPIO.cleanup()
    logger.info("Đã giải phóng GPIO. Thoát chương trình.")
    sys.exit(0)


# === ĐIỂM BẮT ĐẦU CHƯƠNG TRÌNH ===
def main():
    """Khởi tạo phần cứng và chạy Flask server."""
    global pwm_left, pwm_right, camera

    # Đăng ký signal handler để dọn dẹp khi Ctrl+C
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        # Khởi tạo GPIO
        pwm_left, pwm_right = setup_gpio()

        # Khởi tạo camera
        camera = setup_camera()

        # Khởi chạy watchdog thread (chạy nền, tự tắt khi chương trình chính thoát)
        wd_thread = threading.Thread(
            target=watchdog_thread,
            args=(pwm_left, pwm_right),
            daemon=True
        )
        wd_thread.start()
        logger.info(f"Watchdog đã bật (timeout: {WATCHDOG_TIMEOUT}s)")

        # Chạy Flask server
        logger.info("=" * 50)
        logger.info("ROBOT SERVER ĐANG CHẠY")
        logger.info("Đợi lệnh từ AI Server...")
        logger.info("Nhấn Ctrl+C để dừng")
        logger.info("=" * 50)

        app.run(host='0.0.0.0', port=5000, threaded=True)

    except Exception as e:
        logger.critical(f"Lỗi khởi tạo: {e}")
        cleanup()


if __name__ == '__main__':
    main()
