# File: mock_pi_server.py
# Environment: Personal computer (Simulation)
# Description: Mock Raspberry Pi server for testing AI logic on a computer
#              WITHOUT real hardware (no Pi, motor, or GPIO needed).
#              - Uses laptop webcam instead of PiCamera
#              - Prints motor commands to console instead of controlling real GPIO
#              - If no webcam is available, generates mock frames for testing
# -----------------------------------------------------------------------

import time
import signal
import sys
import logging

import cv2
import numpy as np
from flask import Flask, Response, request

# === LOGGING CONFIGURATION ===
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Suppress default Flask logging
werkzeug_log = logging.getLogger('werkzeug')
werkzeug_log.setLevel(logging.ERROR)

# === CONFIGURATION ===
CAMERA_INDEX = 0  # Webcam index (0 = default webcam)
CAMERA_WIDTH = 320  # Image width (pixels)
CAMERA_HEIGHT = 240  # Image height (pixels)
JPEG_QUALITY = 50  # JPEG image quality (0-100)
USE_MOCK_FRAME = False  # Flag: True if no webcam found, use mock frames


# === MOCK MOTOR FUNCTIONS ===
# These functions ONLY print to console, no real hardware control
def go_forward():
    """Simulate forward command"""
    logger.info("[MOTOR] Moving FORWARD (Left: FORWARD | Right: FORWARD)")


def stop_car():
    """Simulate stop command"""
    logger.info("[MOTOR] STOPPED")


def turn_left():
    """Simulate turn left command"""
    logger.info("[MOTOR] Turning LEFT (Left: REVERSE | Right: FORWARD)")


def turn_right():
    """Simulate turn right command"""
    logger.info("[MOTOR] Turning RIGHT (Left: FORWARD | Right: REVERSE)")

def go_backward():
    """Simulate reverse command"""
    logger.info("[MOTOR] Reversing (Left: REVERSE | Right: REVERSE)")


# === CAMERA INITIALIZATION ===
def setup_camera():
    """
    Try to open webcam. If no webcam is available (e.g., running on a
    headless server), switch to mock frame mode.

    Returns:
        cv2.VideoCapture | None: Camera object, or None if using mock
    """
    global USE_MOCK_FRAME

    camera = cv2.VideoCapture(CAMERA_INDEX)

    if not camera.isOpened():
        logger.warning("=" * 50)
        logger.warning("No webcam found!")
        logger.warning("Switching to MOCK FRAME mode")
        logger.warning("(Black frame + text, sufficient for AI logic testing)")
        logger.warning("=" * 50)
        USE_MOCK_FRAME = True
        return None

    # Set webcam resolution
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    logger.info(f"Webcam ready ({CAMERA_WIDTH}x{CAMERA_HEIGHT})")
    return camera


def generate_mock_frame():
    """
    Generate a mock frame when no webcam is available.
    Includes: gray gradient background + status text + timestamp.
    Bright enough so the AI server won't trigger 'image too dark' mode.

    Returns:
        numpy.ndarray: BGR image 320x240
    """
    # Create gray gradient background (dark to light) for sufficient average brightness
    frame = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
    for y in range(CAMERA_HEIGHT):
        brightness = int(80 + (y / CAMERA_HEIGHT) * 100)  # 80-180
        frame[y, :] = [brightness, brightness, brightness]

    # Add status text
    cv2.putText(
        frame, "MOCK CAMERA", (60, 100),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
    )
    cv2.putText(
        frame, "No webcam detected", (50, 140),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1
    )

    # Add timestamp to confirm frames are being updated
    timestamp = time.strftime("%H:%M:%S")
    cv2.putText(
        frame, timestamp, (110, 200),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2
    )

    return frame


def read_frame(camera):
    """
    Read one frame from webcam or generate a mock frame.

    Args:
        camera: cv2.VideoCapture object or None

    Returns:
        tuple: (success: bool, frame: numpy.ndarray)
    """
    if USE_MOCK_FRAME or camera is None:
        return True, generate_mock_frame()

    try:
        success, frame = camera.read()
        if not success:
            logger.warning("Webcam returned empty frame, using mock frame instead.")
            return True, generate_mock_frame()
        return True, frame
    except Exception as e:
        logger.error(f"Error reading webcam: {e}")
        return True, generate_mock_frame()


# === FLASK APPLICATION ===
app = Flask(__name__)

# Global camera variable
camera = None


@app.route('/video_feed')
def video_feed():
    """
    MJPEG video streaming over HTTP (for live viewing in browser).
    Access: http://127.0.0.1:5000/video_feed
    """

    def generate_frames():
        """Generator: continuously read frames and send as MJPEG stream."""
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
    Mock motor control API.
    Receives commands via ?cmd=go|stop|left|right
    Only prints to console, no real hardware control.
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
        logger.warning(f"Received invalid command: '{cmd}'")
        return f"Invalid command: {cmd}", 400

    return "OK"


@app.route('/snapshot')
def snapshot():
    """
    Quick snapshot (used by AI server to fetch frames for analysis).
    Returns a single JPEG image.
    - If webcam is available, captures from webcam
    - If no webcam, returns a mock frame
    """
    success, frame = read_frame(camera)

    if success and frame is not None:
        ret, buffer = cv2.imencode(
            '.jpg', frame,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        if ret:
            return Response(buffer.tobytes(), mimetype='image/jpeg')

    logger.error("Failed to create snapshot image!")
    return "Camera Error", 500

# --- MOCK ULTRASONIC SENSOR ---
@app.route('/distance')
def get_distance():

    fake_distance = 100
    return str(fake_distance)


@app.route('/')
def index():
    """Home page displaying mock server status."""
    mode = "Webcam" if not USE_MOCK_FRAME else "Mock Frame"
    return (
        "<h1>Mock Pi Server (Simulation)</h1>"
        f"<p>Camera mode: {mode}</p>"
        "<p>API endpoints:</p>"
        "<ul>"
        "<li><a href='/snapshot'>/snapshot</a> - Capture image</li>"
        "<li><a href='/video_feed'>/video_feed</a> - View video</li>"
        "<li>/control?cmd=go|stop|left|right - Control (simulated)</li>"
        "</ul>"
    )


def cleanup(sig=None, frame=None):
    """
    Clean up resources when shutting down.
    Release webcam so other programs can use it.
    """
    logger.info("Cleaning up resources...")

    if camera is not None:
        try:
            camera.release()
            logger.info("Webcam released.")
        except Exception as e:
            logger.warning(f"Error releasing webcam: {e}")

    logger.info("Mock server exited.")
    sys.exit(0)


# === PROGRAM ENTRY POINT ===
def main():
    """Initialize mock camera and run Flask server."""
    global camera

    # Register signal handlers for cleanup on Ctrl+C and kill
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Initialize webcam (or switch to mock if unavailable)
    camera = setup_camera()

    # Display server info
    logger.info("=" * 50)
    logger.info("MOCK PI SERVER RUNNING (Simulation)")
    logger.info("Address: http://127.0.0.1:5000")
    logger.info("Mode: " + ("Webcam" if not USE_MOCK_FRAME else "Mock Frame"))
    logger.info("Waiting for commands from AI Server...")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 50)

    # Run Flask server on localhost
    app.run(host='127.0.0.1', port=5000, threaded=True)


if __name__ == '__main__':
    main()
