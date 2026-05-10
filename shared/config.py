"""
AutoCar — Centralized Configuration
All hardware pins, MQTT topics, tuning parameters, and thresholds.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════
#  MQTT Broker
# ═══════════════════════════════════════════════════════════════════
MQTT_BROKER_IP = os.getenv("MQTT_BROKER_IP", "127.0.0.1")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
MQTT_KEEPALIVE = 60

# ═══════════════════════════════════════════════════════════════════
#  MQTT Topics
# ═══════════════════════════════════════════════════════════════════

class Topics:
    """Centralized MQTT topic registry."""

    # Pi → AI: camera frame (JPEG bytes)
    CAMERA_FRAME = "autocar/camera/frame"

    # Pi → AI: ultrasonic distance
    SENSOR_ULTRASONIC = "autocar/sensor/ultrasonic"

    # AI → Pi: motor command
    COMMAND_MOTOR = "autocar/command/motor"

    # Pi → ALL: FSM state
    STATE_FSM = "autocar/state/fsm"

    # AI → ALL: brain/BT state
    STATE_BRAIN = "autocar/state/brain"

    # Both → ALL: health/heartbeat
    STATE_HEALTH = "autocar/state/health"

    # Any → Pi: emergency stop (empty payload)
    CONTROL_EMERGENCY_STOP = "autocar/control/emergency_stop"

    # GUI → AI: toggle AI on/off
    CONTROL_AI_TOGGLE = "autocar/control/ai_toggle"

    # Pi → ALL: online/offline status (uses MQTT LWT)
    STATUS_PI = "autocar/status/pi"


# ═══════════════════════════════════════════════════════════════════
#  GPIO Pins (BCM mode) — Raspberry Pi
# ═══════════════════════════════════════════════════════════════════
MOTOR_LEFT_EN   = 25
MOTOR_LEFT_IN1  = 24
MOTOR_LEFT_IN2  = 23

MOTOR_RIGHT_EN  = 17
MOTOR_RIGHT_IN1 = 27
MOTOR_RIGHT_IN2 = 22

TRIG_PIN = 5
ECHO_PIN = 6

# ═══════════════════════════════════════════════════════════════════
#  Motor Defaults
# ═══════════════════════════════════════════════════════════════════
DEFAULT_SPEED = 80          # PWM duty cycle (0-100)
PWM_FREQUENCY = 1000        # Hz
WATCHDOG_TIMEOUT = 3.0      # Seconds without command → auto-stop

# ═══════════════════════════════════════════════════════════════════
#  Camera
# ═══════════════════════════════════════════════════════════════════
CAMERA_WIDTH  = 320
CAMERA_HEIGHT = 240
JPEG_QUALITY  = 50
CAMERA_FPS    = 10           # Frames published per second via MQTT
CAMERA_MAX_RETRIES = 3
CAMERA_RETRY_DELAY = 3.0    # Seconds between retry attempts

# ═══════════════════════════════════════════════════════════════════
#  Ultrasonic Sensor
# ═══════════════════════════════════════════════════════════════════
ULTRASONIC_PUBLISH_HZ = 5    # Readings published per second
ULTRASONIC_TIMEOUT = 0.04    # Seconds — max wait for echo
ULTRASONIC_MAX_DISTANCE = 999.0  # cm — returned on timeout

# ═══════════════════════════════════════════════════════════════════
#  AI Perception Thresholds
# ═══════════════════════════════════════════════════════════════════
DANGER_AREA_THRESHOLD     = 8000    # px² — obstacle area to trigger danger
DEAD_END_AREA_THRESHOLD   = 30000   # px² — obstacle area to trigger dead-end
BRIGHTNESS_THRESHOLD      = 15      # Mean pixel value — below = "blind"
TTC_EXPANSION_THRESHOLD   = 8000    # px² per frame — rapid approach detection
MODEL_CONFIDENCE          = 0.6     # YOLOv5 confidence threshold

# ═══════════════════════════════════════════════════════════════════
#  Behavior Tree Parameters
# ═══════════════════════════════════════════════════════════════════
CONFIRM_FRAMES = 3          # Consecutive detections before acting
CLEAR_FRAMES   = 3          # Consecutive clear frames before resuming
MAX_CAMERA_FAILURES = 5     # Frames before emergency stop

# Danger level boundaries (0.0 = clear, 1.0 = critical)
DANGER_LEVEL_CAUTION = 0.2  # Below this → free cruise
DANGER_LEVEL_DANGER  = 0.5  # Above this → active avoidance

# Speed mapping for cautious cruise
CAUTIOUS_SPEED_MAX = 80     # Speed at danger_level = CAUTION
CAUTIOUS_SPEED_MIN = 40     # Speed at danger_level = DANGER

# Dead-end recovery timings
ESCAPE_REVERSE_DURATION  = 1.2   # Seconds
ESCAPE_PIVOT_DURATION    = 1.0   # Seconds
ESCAPE_STOP_DURATION     = 0.3   # Seconds

# AEB cooldown
AEB_COOLDOWN = 1.5          # Seconds after emergency brake

# Ultrasonic thresholds for fusion
ULTRASONIC_EMERGENCY_CM = 8.0    # Below → collision imminent
ULTRASONIC_DEAD_END_CM  = 10.0   # Below → trapped
ULTRASONIC_DANGER_CM    = 25.0   # Below → danger

# ═══════════════════════════════════════════════════════════════════
#  Web Dashboard
# ═══════════════════════════════════════════════════════════════════
DASHBOARD_PORT = 8081
DASHBOARD_HOST = "0.0.0.0"

# Pi MJPEG endpoint (for Web GUI video feed)
PI_IP = os.getenv("CAR_IP", "127.0.0.1")
PI_MJPEG_URL = f"http://{PI_IP}:5000/video_feed"
