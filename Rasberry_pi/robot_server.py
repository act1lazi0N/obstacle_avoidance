import time
import signal
import sys
import threading
import logging
import subprocess
import os
import cv2

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

# ── GPIO Pinout ────────────────────────────────────────────────
MOTOR_LEFT_EN  = 25
MOTOR_LEFT_IN1 = 24
MOTOR_LEFT_IN2 = 23
 
MOTOR_RIGHT_EN  = 17
MOTOR_RIGHT_IN1 = 27
MOTOR_RIGHT_IN2 = 22
 
DEFAULT_SPEED    = 80
WATCHDOG_TIMEOUT = 3.0
 
CAMERA_WIDTH  = 320
CAMERA_HEIGHT = 240
JPEG_QUALITY  = 50
 
TRIG_PIN = 5
ECHO_PIN = 6
# ──────────────────────────────────────────────────────────────
# Thread-safety locks to prevent race conditions
motor_lock = threading.Lock()
sonic_lock = threading.Lock()
camera_lock = threading.Lock()
_cmd_lock = threading.Lock()

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(MOTOR_LEFT_EN, GPIO.OUT)
    GPIO.setup(MOTOR_LEFT_IN1, GPIO.OUT)
    GPIO.setup(MOTOR_LEFT_IN2, GPIO.OUT)

    GPIO.setup(MOTOR_RIGHT_EN, GPIO.OUT)
    GPIO.setup(MOTOR_RIGHT_IN1, GPIO.OUT)
    GPIO.setup(MOTOR_RIGHT_IN2, GPIO.OUT)

    # Set initial state: any HIGH pin would cause motors to spin by default
    GPIO.output(MOTOR_LEFT_IN1,  GPIO.LOW)
    GPIO.output(MOTOR_LEFT_IN2,  GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
    GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)

    pwm_left = GPIO.PWM(MOTOR_LEFT_EN, 1000)
    pwm_right = GPIO.PWM(MOTOR_RIGHT_EN, 1000)

    # Ultrasonic sensor
    GPIO.setup(TRIG_PIN, GPIO.OUT)
    GPIO.setup(ECHO_PIN, GPIO.IN)
    GPIO.output(TRIG_PIN, False)

    pwm_left.start(0)
    pwm_right.start(0)

    logger.info("GPIO initialized for Motor & Ultrasonic.")
    return pwm_left, pwm_right

# ─────────────────────────────────────────────────────────────────────────────
# Motor control functions — all wrapped with motor_lock
#
# L298N truth table (applies to both channels):
#   IN1=HIGH, IN2=LOW  -> Forward
#   IN1=LOW,  IN2=HIGH -> Reverse
#   IN1=HIGH, IN2=HIGH -> Brake (active stop)
# ─────────────────────────────────────────────────────────────────────────────
def go_forward(pwm_left, pwm_right):
    with motor_lock:
        GPIO.output(MOTOR_LEFT_IN1,  GPIO.HIGH)
        GPIO.output(MOTOR_LEFT_IN2,  GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
        pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
        pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Moving forward")

def turn_left(pwm_left, pwm_right):
    with motor_lock:
        GPIO.output(MOTOR_LEFT_IN1,  GPIO.LOW)   # Left wheel: reverse
        GPIO.output(MOTOR_LEFT_IN2,  GPIO.HIGH)
        GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)  # Right wheel: forward
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
        pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
        pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Turning left")

def turn_right(pwm_left, pwm_right):
    with motor_lock:
        GPIO.output(MOTOR_LEFT_IN1,  GPIO.HIGH)  # Left wheel: forward
        GPIO.output(MOTOR_LEFT_IN2,  GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)   # Right wheel: reverse
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH)
        pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
        pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Turning right")

def go_backward(pwm_left, pwm_right):
    with motor_lock:
        GPIO.output(MOTOR_LEFT_IN1,  GPIO.LOW)
        GPIO.output(MOTOR_LEFT_IN2,  GPIO.HIGH)
        GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH)
        pwm_left.ChangeDutyCycle(DEFAULT_SPEED)
        pwm_right.ChangeDutyCycle(DEFAULT_SPEED)
    logger.info("[MOTOR] Going backward")

def stop_car(pwm_left, pwm_right):
    with motor_lock:
        # Active brake: IN1=IN2=HIGH, max PWM -> immediate stop
        GPIO.output(MOTOR_LEFT_IN1,  GPIO.HIGH)
        GPIO.output(MOTOR_LEFT_IN2,  GPIO.HIGH)
        GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH)
        pwm_left.ChangeDutyCycle(100)
        pwm_right.ChangeDutyCycle(100)

        # After 50ms disable PWM: car has fully stopped, release motors
    time.sleep(0.05)
    with motor_lock:
        pwm_left.ChangeDutyCycle(0)
        pwm_right.ChangeDutyCycle(0)

        # Return to coast-safe: set IN pins LOW after PWM = 0
        GPIO.output(MOTOR_LEFT_IN1,  GPIO.LOW)
        GPIO.output(MOTOR_LEFT_IN2,  GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
    logger.info("[MOTOR] Stopped (active brake)")

def release_camera_pipeline():
    """
    Kill any stale processes holding the libcamera pipeline.
    This is necessary when a previous robot_server was killed abruptly
    (Ctrl+Z, kill -9, power loss) and didn't call cleanup().
    Skips the current process so we don't kill ourselves.
    """
    my_pid = os.getpid()
    targets = ['libcamera-vid', 'libcamera-still', 'rpicam']
    killed = []

    try:
        # List all processes, filter for camera-related ones
        result = subprocess.run(
            ['ps', 'aux'], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            # Skip header line
            if 'PID' in line and 'COMMAND' in line:
                continue
            # Check if any target keyword matches
            if any(t in line for t in targets):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1])
                        if pid != my_pid:
                            os.kill(pid, signal.SIGKILL)
                            killed.append(pid)
                    except (ValueError, ProcessLookupError, PermissionError):
                        pass
    except Exception as e:
        logger.warning(f"Could not scan for stale processes: {e}")

    if killed:
        logger.info(f"Killed stale camera processes: {killed}")
        time.sleep(2)  # Wait for kernel to release /dev/video*
    else:
        logger.info("No stale camera processes found.")


def setup_camera(max_retries=3, retry_delay=3.0):
    """
    Initialize PiCamera2 with automatic pipeline release and retry.
    Steps:
        1. Kill any stale processes holding the camera
        2. Attempt to init (up to max_retries times)
    """
    release_camera_pipeline()

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Camera init attempt {attempt}/{max_retries}...")
            camera = Picamera2()
            config = camera.create_preview_configuration(
                main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"}
            )
            camera.configure(config)
            camera.start()
            try:
                camera.set_controls({"Saturation": 0.0})
                logger.info("Saturation set to 0.0 (grayscale)")
            except Exception as e:
                logger.warning(f"Saturation control not available: {e}")
                logger.warning("Will convert to grayscale via OpenCV instead.")

            time.sleep(2)
            logger.info(f"PiCamera2 ready ({CAMERA_WIDTH}x{CAMERA_HEIGHT}, grayscale)")
            return camera

        except Exception as e:
            logger.error(f"Camera init failed (attempt {attempt}): {e}")
            try:
                camera.close()
            except Exception:
                pass
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                logger.critical("All camera init attempts failed. Exiting.")
                raise

def update_last_command_time():
    global last_command_time
    with _cmd_lock:
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

def get_distance():
    with sonic_lock:
        GPIO.output(TRIG_PIN, True)
        time.sleep(0.00001)
        GPIO.output(TRIG_PIN, False)

        start_time = time.time()
        stop_time  = time.time()
        timeout    = start_time + 0.04

        while GPIO.input(ECHO_PIN) == 0:
            start_time = time.time()
            if start_time > timeout:
                time.sleep(0.06)
                return 999

        while GPIO.input(ECHO_PIN) == 1:
            stop_time = time.time()
            if stop_time > timeout:
                time.sleep(0.06)
                return 999

        elapsed  = stop_time - start_time
        distance = (elapsed * 34300) / 2
        time.sleep(0.06)

    return round(distance, 2)

@app.route('/control', methods=['GET'])
def control():
    global last_command_time
    cmd = request.args.get('cmd', '').lower()
    last_command_time = time.time()

    if cmd == 'go':
        go_forward(pwm_left, pwm_right)
    elif cmd == 'backward':
        go_backward(pwm_left, pwm_right)
    elif cmd == 'stop':
        stop_car(pwm_left, pwm_right)
    elif cmd == 'left':
        turn_left(pwm_left, pwm_right)
    elif cmd == 'right':
        turn_right(pwm_left, pwm_right)
    else:
        return "Invalid", 400
    return "OK"

@app.route('/distance')
def distance_api():
    return str(round(get_distance(), 2))

@app.route('/snapshot')
def snapshot():
    try:
        with camera_lock:
            frame = camera.capture_array()
        # Convert to grayscale then back to BGR for consistent output
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        frame_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        ret, buffer = cv2.imencode('.jpg', frame_bgr,
                                   [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ret:
            return Response(buffer.tobytes(), mimetype='image/jpeg')
        logger.error("Failed to encode JPEG image.")
        return "Image encoding error", 500
    except Exception as e:
        logger.error(f"Error capturing snapshot: {e}")
        return f"Camera error: {e}", 500

@app.route('/video_feed')
def video_feed():
    def generate_frames():
        while True:
            time.sleep(0.033)
            try:
                with camera_lock:
                    frame = camera.capture_array()
                # Convert to grayscale then back to BGR for consistent output
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                frame_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                ret, buffer = cv2.imencode('.jpg', frame_bgr,
                                           [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
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
 
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

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
    if pwm_left is not None and pwm_right is not None:
        stop_car(pwm_left, pwm_right)
    if camera is not None:
        try:
            camera.stop()
            camera.close()
            logger.info("Camera stopped and closed.")
        except Exception as e:
            logger.warning(f"Error stopping camera: {e}")
    try:
        GPIO.cleanup()
        logger.info("GPIO cleaned up. Exiting program.")
    except Exception:
        pass
    sys.exit(0)

def main():
    global pwm_left, pwm_right, camera

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Init GPIO first (always safe)
    try:
        pwm_left, pwm_right = setup_gpio()
    except Exception as e:
        logger.critical(f"GPIO initialization error: {e}")
        GPIO.cleanup()
        sys.exit(1)

    # Init camera (with retry for post-pkill pipeline release)
    try:
        camera = setup_camera()
    except Exception as e:
        logger.critical(f"Camera initialization failed after all retries: {e}")
        cleanup()

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

if __name__ == '__main__':
    main()