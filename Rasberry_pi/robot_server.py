import time
import signal
import sys
import threading
import logging
import subprocess
import os
import cv2

from flask import Flask, Response, request
last_motor_state = ""
try:
    import RPi.GPIO as GPIO
except ImportError:
    print("RPi.GPIO not found!")
    sys.exit(1)

try:
    from picamera2 import Picamera2
except ImportError:
    print("picamera2 not found!")
    sys.exit(1)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)

werkzeug_log = logging.getLogger('werkzeug')
werkzeug_log.setLevel(logging.ERROR)

# =========================================================
# GPIO PINOUT
# =========================================================

# LEFT MOTOR
MOTOR_LEFT_EN  = 25
MOTOR_LEFT_IN1 = 24
MOTOR_LEFT_IN2 = 23

# RIGHT MOTOR
MOTOR_RIGHT_EN  = 17
MOTOR_RIGHT_IN1 = 27
MOTOR_RIGHT_IN2 = 22

# LED
LED_LEFT  = 26
LED_RIGHT = 20
LED_BACK  = 21

# ULTRASONIC
#Cam bien truoc
TRIG_PIN = 5
ECHO_PIN = 6

#Cam bien sau
REAR_TRIG_PIN = 18
REAR_ECHO_PIN = 12
# =========================================================
# CONFIG
# =========================================================

DEFAULT_SPEED = 70
BACKWARD_SPEED = 55
TURN_SPEED = 65

WATCHDOG_TIMEOUT = 3.0

CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240
JPEG_QUALITY = 50

# =========================================================
# GLOBALS
# =========================================================

motor_lock = threading.Lock()
camera_lock = threading.Lock()
sonic_lock = threading.Lock()
cmd_lock = threading.Lock()

last_command_time = time.time()

pwm_left = None
pwm_right = None
camera = None

app = Flask(__name__)

# =========================================================
# GPIO SETUP
# =========================================================

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    pins = [
        MOTOR_LEFT_EN,
        MOTOR_LEFT_IN1,
        MOTOR_LEFT_IN2,
        MOTOR_RIGHT_EN,
        MOTOR_RIGHT_IN1,
        MOTOR_RIGHT_IN2,
        LED_LEFT,
        LED_RIGHT,
        LED_BACK,
        TRIG_PIN
    ]

    for pin in pins:
        GPIO.setup(pin, GPIO.OUT)

    GPIO.setup(ECHO_PIN, GPIO.IN)

    GPIO.setup(REAR_TRIG_PIN, GPIO.OUT)
    GPIO.setup(REAR_ECHO_PIN, GPIO.IN)

    GPIO.output(REAR_TRIG_PIN, GPIO.LOW)

    # Initial LOW
    for pin in pins:
        GPIO.output(pin, GPIO.LOW)

    pwm_l = GPIO.PWM(MOTOR_LEFT_EN, 1000)
    pwm_r = GPIO.PWM(MOTOR_RIGHT_EN, 1000)

    pwm_l.start(0)
    pwm_r.start(0)

    logger.info("GPIO initialized")

    return pwm_l, pwm_r

# =========================================================
# LED CONTROL
# =========================================================

def reset_leds():
    GPIO.output(LED_LEFT, GPIO.LOW)
    GPIO.output(LED_RIGHT, GPIO.LOW)
    GPIO.output(LED_BACK, GPIO.LOW)

# =========================================================
# MOTOR CONTROL
# =========================================================

def set_motor(
    left_in1,
    left_in2,
    right_in1,
    right_in2,
    left_speed,
    right_speed
):
    with motor_lock:

        GPIO.output(MOTOR_LEFT_IN1, left_in1)
        GPIO.output(MOTOR_LEFT_IN2, left_in2)

        GPIO.output(MOTOR_RIGHT_IN1, right_in1)
        GPIO.output(MOTOR_RIGHT_IN2, right_in2)

        pwm_left.ChangeDutyCycle(left_speed)
        pwm_right.ChangeDutyCycle(right_speed)

def go_forward():
    reset_leds()

    set_motor(
        GPIO.HIGH, GPIO.LOW,
        GPIO.HIGH, GPIO.LOW,
        BACKWARD_SPEED,
        BACKWARD_SPEED
    )

    global last_motor_state

    if last_motor_state != "FORWARD":
        logger.info("[MOTOR] FORWARD")

    last_motor_state = "FORWARD"

def go_backward():
    reset_leds()

    GPIO.output(LED_BACK, GPIO.HIGH)

    set_motor(
        GPIO.LOW, GPIO.HIGH,
        GPIO.LOW, GPIO.HIGH,
        DEFAULT_SPEED,
        DEFAULT_SPEED
    )

    global last_motor_state

    if last_motor_state != "BACKWARD":
        logger.info("[MOTOR] BACKWARD")

    last_motor_state = "BACKWARD"

def turn_left():
    reset_leds()

    GPIO.output(LED_LEFT, GPIO.HIGH)

    set_motor(
        GPIO.LOW, GPIO.HIGH,
        GPIO.HIGH, GPIO.LOW,
        TURN_SPEED,
        TURN_SPEED
    )

    global last_motor_state

    if last_motor_state != "LEFT":
        logger.info("[MOTOR] LEFT")

    last_motor_state = "LEFT"

def turn_right():
    reset_leds()

    GPIO.output(LED_RIGHT, GPIO.HIGH)

    set_motor(
        GPIO.HIGH, GPIO.LOW,
        GPIO.LOW, GPIO.HIGH,
        TURN_SPEED,
        TURN_SPEED
    )

    global last_motor_state

    if last_motor_state != "RIGHT":
        logger.info("[MOTOR] RIGHT")

    last_motor_state = "RIGHT"

def stop_car():

    reset_leds()

    with motor_lock:

        # Active brake
        GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
        GPIO.output(MOTOR_LEFT_IN2, GPIO.HIGH)

        GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH)

        pwm_left.ChangeDutyCycle(100)
        pwm_right.ChangeDutyCycle(100)

        time.sleep(0.05)

        pwm_left.ChangeDutyCycle(0)
        pwm_right.ChangeDutyCycle(0)

        GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
        GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)

        GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)

    global last_motor_state

    if last_motor_state != "STOP":
        logger.info("[MOTOR] STOP")

    last_motor_state = "STOP"

# =========================================================
# COMMAND TIMER
# =========================================================

def update_last_command_time():
    global last_command_time

    with cmd_lock:
        last_command_time = time.time()

# =========================================================
# WATCHDOG
# =========================================================

def watchdog_thread():

    global last_command_time
    global last_motor_state

    watchdog_triggered = False

    while True:

        with cmd_lock:
            elapsed = time.time() - last_command_time

        # Timeout detected
        if elapsed > WATCHDOG_TIMEOUT:

            # Only stop ONCE
            if not watchdog_triggered:

                if last_motor_state != "STOP":

                    logger.warning(
                        f"[WATCHDOG] Timeout {WATCHDOG_TIMEOUT}s -> STOP"
                    )

                    stop_car()

                watchdog_triggered = True

        else:
            watchdog_triggered = False

        time.sleep(0.2)

# =========================================================
# ULTRASONIC
# =========================================================
#doc khoang cach truoc
def get_distance():

    with sonic_lock:

        GPIO.output(TRIG_PIN, False)
        time.sleep(0.0002)

        GPIO.output(TRIG_PIN, True)
        time.sleep(0.00001)
        GPIO.output(TRIG_PIN, False)

        pulse_start = time.time()
        timeout = pulse_start + 0.03

        while GPIO.input(ECHO_PIN) == 0:

            pulse_start = time.time()

            if pulse_start > timeout:
                return 999

        pulse_end = time.time()

        while GPIO.input(ECHO_PIN) == 1:

            pulse_end = time.time()

            if pulse_end > timeout:
                return 999

        duration = pulse_end - pulse_start

        distance = duration * 17150

        if distance <= 0 or distance > 400:
            return 999

        return round(distance, 2)
#doc khoang cach sau
def get_rear_distance():
    with sonic_lock:

        GPIO.output(TRIG_PIN, False)
        time.sleep(0.0002)

        GPIO.output(TRIG_PIN, True)
        time.sleep(0.00001)
        GPIO.output(TRIG_PIN, False)

        pulse_start = time.time()
        timeout = pulse_start + 0.03

        while GPIO.input(ECHO_PIN) == 0:

            pulse_start = time.time()

            if pulse_start > timeout:
                return 999

        pulse_end = time.time()

        while GPIO.input(ECHO_PIN) == 1:

            pulse_end = time.time()

            if pulse_end > timeout:
                return 999

        duration = pulse_end - pulse_start

        distance = duration * 17150

        if distance <= 0 or distance > 400:
            return 999

        return round(distance, 2)

# =========================================================
# CAMERA
# =========================================================

def release_camera_pipeline():

    targets = ['libcamera', 'rpicam']

    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True
        )

        for line in result.stdout.splitlines():

            if any(t in line for t in targets):

                parts = line.split()

                if len(parts) > 1:
                    try:
                        pid = int(parts[1])

                        if pid != os.getpid():
                            os.kill(pid, signal.SIGKILL)

                    except:
                        pass

    except Exception as e:
        logger.warning(f"Camera cleanup failed: {e}")

def setup_camera():

    release_camera_pipeline()

    cam = Picamera2()

    config = cam.create_preview_configuration(
        main={
            "size": (CAMERA_WIDTH, CAMERA_HEIGHT),
            "format": "RGB888"
        }
    )

    cam.configure(config)

    cam.start()

    time.sleep(2)

    logger.info("Camera ready")

    return cam

# =========================================================
# FLASK ROUTES
# =========================================================

@app.route('/control')
def control():
    cmd = request.args.get('cmd', '').lower()
    global last_command
    # Ignore duplicate command
    if cmd == last_command:
        update_last_command_time()

        return "IGNORED"

    last_command = cmd

    update_last_command_time()

    try:

        if cmd == 'go':
            go_forward()


        elif cmd == 'backward':
            rear_distance = get_rear_distance()
            if rear_distance < 15:
                logger.warning(
                    f"Rear obstacle detected: {rear_distance} cm"
                )
                stop_car()
                return "REAR OBSTACLE", 403
            go_backward()

        elif cmd == 'left':
            turn_left()

        elif cmd == 'right':
            turn_right()

        elif cmd == 'stop':
            stop_car()

        else:
            return "INVALID COMMAND", 400

        return "OK"

    except Exception as e:
        logger.error(e)
        return str(e), 500

#api cho cam bien truoc
@app.route('/distance')
def distance_api():
    return str(get_distance())

#api cho cam bien sau
@app.route('/rear_distance')
def rear_distance_api():
    return str(get_rear_distance())

@app.route('/snapshot')
def snapshot():

    try:

        with camera_lock:
            frame = camera.capture_array()

        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        ret, buffer = cv2.imencode(
            '.jpg',
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )

        if not ret:
            return "Encode failed", 500

        return Response(
            buffer.tobytes(),
            mimetype='image/jpeg'
        )

    except Exception as e:
        logger.error(e)
        return str(e), 500

@app.route('/video_feed')
def video_feed():

    def generate():

        while True:

            try:

                with camera_lock:
                    frame = camera.capture_array()

                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

                frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

                ret, buffer = cv2.imencode(
                    '.jpg',
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                )

                if ret:

                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' +
                        buffer.tobytes() +
                        b'\r\n'
                    )

                time.sleep(0.03)

            except Exception as e:
                logger.error(e)
                continue

    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/')
def index():

    return """
    <h1>Robot Server Running</h1>

    <ul>
        <li>/control?cmd=go</li>
        <li>/control?cmd=backward</li>
        <li>/control?cmd=left</li>
        <li>/control?cmd=right</li>
        <li>/control?cmd=stop</li>
        <li>/distance</li>
        <li>/rear_distance</li>
        <li>/snapshot</li>
        <li>/video_feed</li>
    </ul>
    """

# =========================================================
# CLEANUP
# =========================================================

def cleanup(sig=None, frame=None):

    logger.info("Cleaning up...")

    try:
        stop_car()

        pwm_left.stop()
        pwm_right.stop()

    except:
        pass

    try:
        if camera:
            camera.stop()
            camera.close()

    except:
        pass

    GPIO.cleanup()

    sys.exit(0)

# =========================================================
# MAIN
# =========================================================

def main():

    global pwm_left
    global pwm_right
    global camera

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    pwm_left, pwm_right = setup_gpio()

    camera = setup_camera()

    watchdog = threading.Thread(
        target=watchdog_thread,
        daemon=True
    )

    watchdog.start()

    logger.info("=" * 50)
    logger.info("ROBOT SERVER STARTED")
    logger.info("=" * 50)

    app.run(
        host='0.0.0.0',
        port=5000,
        threaded=False
    )

if __name__ == '__main__':
    main()
