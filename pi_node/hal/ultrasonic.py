"""
AutoCar — Ultrasonic Sensor (HC-SR04) HAL

Measures distance using a single TRIG/ECHO ultrasonic sensor.
Thread-safe with timeout protection.
"""

import time
import threading
import logging

from shared.config import (
    TRIG_PIN, ECHO_PIN,
    ULTRASONIC_TIMEOUT, ULTRASONIC_MAX_DISTANCE,
)

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False
    logger.warning("RPi.GPIO not available — ultrasonic returns mock distance.")


class UltrasonicSensor:
    """
    HC-SR04 ultrasonic distance sensor.

    Returns distance in centimeters. Thread-safe.
    On timeout or error, returns ULTRASONIC_MAX_DISTANCE (999.0).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._initialized = False

    def setup(self) -> None:
        """Initialize GPIO pins for TRIG and ECHO."""
        if not _HAS_GPIO:
            logger.info("[ULTRASONIC] Mock mode — returning fake distance.")
            self._initialized = True
            return

        GPIO.setup(TRIG_PIN, GPIO.OUT)
        GPIO.setup(ECHO_PIN, GPIO.IN)
        GPIO.output(TRIG_PIN, False)
        time.sleep(0.1)  # Let sensor settle

        self._initialized = True
        logger.info("[ULTRASONIC] Sensor initialized.")

    def measure_distance(self) -> float:
        """
        Take a single distance measurement.

        Returns:
            Distance in centimeters, or ULTRASONIC_MAX_DISTANCE on error.

        Note:
            Blocks for ~60ms minimum due to required inter-measurement delay.
        """
        if not _HAS_GPIO:
            return 100.0  # Mock: 100cm

        with self._lock:
            try:
                # Send 10µs trigger pulse
                GPIO.output(TRIG_PIN, True)
                time.sleep(0.00001)
                GPIO.output(TRIG_PIN, False)

                start_time = time.time()
                timeout = start_time + ULTRASONIC_TIMEOUT

                # Wait for echo to go HIGH
                while GPIO.input(ECHO_PIN) == 0:
                    start_time = time.time()
                    if start_time > timeout:
                        time.sleep(0.06)
                        return ULTRASONIC_MAX_DISTANCE

                # Wait for echo to go LOW
                stop_time = start_time
                while GPIO.input(ECHO_PIN) == 1:
                    stop_time = time.time()
                    if stop_time > timeout:
                        time.sleep(0.06)
                        return ULTRASONIC_MAX_DISTANCE

                # Calculate distance
                elapsed = stop_time - start_time
                distance = (elapsed * 34300) / 2

                # Inter-measurement delay (datasheet recommends 60ms)
                time.sleep(0.06)

                return round(distance, 2)

            except Exception as e:
                logger.error(f"[ULTRASONIC] Measurement error: {e}")
                time.sleep(0.06)
                return ULTRASONIC_MAX_DISTANCE
