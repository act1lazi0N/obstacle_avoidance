import time
import signal
import sys
import threading
import logging

from flask import Flask, Response, request

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("=" * 60)
    print("ERROR: RPi.GPIO library not found!")
    print("This file can only run on a Raspberry Pi.")
    print("To test on a computer, use:")
    print("  python Stimulation/mock_pi_server.py")
    print("=" * 60)
    sys.exit(1)

try:
    from picamera2 import Picamera2
except ImportError:
    print("=" * 60)
    print("ERROR: picamera2 library not found!")
    print("Install: sudo apt install -y python3-picamera2")
    print("=" * 60)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

werkzeug_log = logging.getLogger('werkzeug')
werkzeug_log.setLevel(logging.ERROR)

MOTOR_LEFT_EN = 25
MOTOR_LEFT_IN1 = 24
MOTOR_LEFT_IN2 = 23

MOTOR_RIGHT_EN = 17
MOTOR_RIGHT_IN1 = 27
MOTOR_RIGHT_IN2 = 22

DEFAULT_SPEED = 70
WATCHDOG_TIMEOUT = 3.0

CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240
JPEG_QUALITY = 50

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(MOTOR_LEFT_EN, GPIO.OUT)
    GPIO.setup(MOTOR_LEFT_IN1, GPIO.OUT)
    GPIO.setup(MOTOR_LEFT_IN2, GPIO.OUT)

    GPIO.setup(MOTOR_RIGHT_EN, GPIO.OUT)
    GPIO.setup(MOTOR_RIGHT_IN1, GPIO.OUT)
    GPIO.setup(MOTOR_RIGHT_IN2, GPIO.OUT)

    pwm_left = GPIO.PWM(MOTOR_LEFT_EN, 1000)
    pwm_right = GPIO.PWM(MOTOR_RIGHT_EN, 1000)

    pwm_left.start(0)
    pwm_right.start(0)

    logger.info("GPIO initialized for 2 motors.")
    return pwm_left, pwm_right

def go_forward(pwm_left, pwm_right):
    GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
    pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
    pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Moving forward")

def stop_car(pwm_left, pwm_right):
    GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
    pwm_left.ChangeDutyCycle(0)
    pwm_right.ChangeDutyCycle(0)
    logger.info("[MOTOR] Stopped")

def turn_left(pwm_left, pwm_right):
    GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
    pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
    pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Turning left")

def turn_right(pwm_left, pwm_right):
    GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
    GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH)
    pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
    pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Turning right")

def setup_camera():
    try:
        camera = Picamera2()
        config = camera.create_preview_configuration(
            main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"}
        )
        camera.configure(config)
        camera.start()
        time.sleep(2)
        logger.info(f"PiCamera2 ready ({CAMERA_WIDTH}x{CAMERA_HEIGHT})")
        return camera
    except Exception as e:
        logger.error(f"Failed to initialize camera: {e}")
        raise

last_command_time = time.time()

def watchdog_thread(pwm_left, pwm_right):
    global last_command_time
    was_stopped = False

    while True:
        elapsed = time.time() - last_command_time
        if elapsed > WATCHDOG_TIMEOUT:
            if not was_stopped:
                logger.warning(f"WATCHDOG: No command received in {WATCHDOG_TIMEOUT}s. Stopping car.")
                stop_car(pwm_left, pwm_right)
                was_stopped = True
        else:
            was_stopped = False

        time.sleep(0.5)

app = Flask(__name__)

pwm_left = None
pwm_right = None
camera = None

@app.route('/control', methods=['GET'])
def control():
    global last_command_time
    cmd = request.args.get('cmd', '').lower()
    last_command_time = time.time()

    if cmd == 'go':
        go_forward(pwm_left, pwm_right)
    elif cmd == 'stop':
        stop_car(pwm_left, pwm_right)
    elif cmd == 'left':
        turn_left(pwm_left, pwm_right)
    elif cmd == 'right':
        turn_right(pwm_left, pwm_right)
    else:
        logger.warning(f"Invalid command received: '{cmd}'")
        return f"Invalid command: {cmd}", 400

    return "OK"

@app.route('/snapshot')
def snapshot():
    try:
        import cv2
        frame = camera.capture_array()
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ret, buffer = cv2.imencode(
            '.jpg', frame_bgr,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        if ret:
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        else:
            logger.error("Failed to encode JPEG image.")
            return "Image encoding error", 500
    except Exception as e:
        logger.error(f"Error capturing image: {e}")
        return f"Camera error: {e}", 500

@app.route('/video_feed')
def video_feed():
    def generate_frames():
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
                logger.error(f"Error in video stream: {e}")
                break

    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/')
def index():
    return (
        "<h1>Robot Server (Raspberry Pi)</h1>"
        "<p>API endpoints:</p>"
        "<ul>"
        "<li><a href='/snapshot'>/snapshot</a> - Capture image</li>"
        "<li><a href='/video_feed'>/video_feed</a> - View video</li>"
        "<li>/control?cmd=go|stop|left|right - Control</li>"
        "</ul>"
    )

def cleanup(sig=None, frame=None):
    logger.info("Cleaning up resources...")
    if pwm_left and pwm_right:
        stop_car(pwm_left, pwm_right)
    if camera:
        try:
            camera.stop()
            logger.info("Camera stopped.")
        except Exception as e:
            logger.warning(f"Error stopping camera: {e}")
    GPIO.cleanup()
    logger.info("GPIO cleaned up. Exiting program.")
    sys.exit(0)

def main():
    global pwm_left, pwm_right, camera

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        pwm_left, pwm_right = setup_gpio()
        camera = setup_camera()

        wd_thread = threading.Thread(
            target=watchdog_thread,
            args=(pwm_left, pwm_right),
            daemon=True
        )
        wd_thread.start()
        logger.info(f"Watchdog enabled (timeout: {WATCHDOG_TIMEOUT}s)")

        logger.info("=" * 50)
        logger.info("ROBOT SERVER RUNNING")
        logger.info("Waiting for commands from AI Server...")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 50)

        app.run(host='0.0.0.0', port=5000, threaded=True)

    except Exception as e:
        logger.critical(f"Initialization error: {e}")
        cleanup()

if __name__ == '__main__':
    main()