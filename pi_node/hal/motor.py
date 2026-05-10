"""
AutoCar — Motor Controller (Hardware Abstraction Layer)

Controls two DC motors via L298N driver using Raspberry Pi GPIO.
Supports differential steering for smooth proportional turns.

L298N truth table (per channel):
    IN1=HIGH, IN2=LOW  → Forward
    IN1=LOW,  IN2=HIGH → Reverse
    IN1=HIGH, IN2=HIGH → Brake (active stop)
    IN1=LOW,  IN2=LOW  → Coast (free spin)
"""

import threading
import time
import logging

from shared.config import (
    MOTOR_LEFT_EN, MOTOR_LEFT_IN1, MOTOR_LEFT_IN2,
    MOTOR_RIGHT_EN, MOTOR_RIGHT_IN1, MOTOR_RIGHT_IN2,
    DEFAULT_SPEED, PWM_FREQUENCY,
)

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False
    logger.warning("RPi.GPIO not available — motor commands will be logged only.")


class MotorController:
    """
    Low-level motor control with thread-safety and differential steering.

    All speed values are PWM duty cycle percentages (0–100).
    Steer values range from -1.0 (full left) to +1.0 (full right).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._pwm_left = None
        self._pwm_right = None
        self._initialized = False

    def setup(self) -> None:
        """Initialize GPIO pins and start PWM. Call once at startup."""
        if not _HAS_GPIO:
            logger.info("[MOTOR] Mock mode — no GPIO available.")
            self._initialized = True
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Motor pins
        for pin in [MOTOR_LEFT_EN, MOTOR_LEFT_IN1, MOTOR_LEFT_IN2,
                     MOTOR_RIGHT_EN, MOTOR_RIGHT_IN1, MOTOR_RIGHT_IN2]:
            GPIO.setup(pin, GPIO.OUT)

        # Start with everything off
        for pin in [MOTOR_LEFT_IN1, MOTOR_LEFT_IN2,
                     MOTOR_RIGHT_IN1, MOTOR_RIGHT_IN2]:
            GPIO.output(pin, GPIO.LOW)

        # PWM
        self._pwm_left = GPIO.PWM(MOTOR_LEFT_EN, PWM_FREQUENCY)
        self._pwm_right = GPIO.PWM(MOTOR_RIGHT_EN, PWM_FREQUENCY)
        self._pwm_left.start(0)
        self._pwm_right.start(0)

        self._initialized = True
        logger.info("[MOTOR] GPIO initialized.")

    def cleanup(self) -> None:
        """Release GPIO resources. Call at shutdown."""
        self.coast()
        if _HAS_GPIO and self._initialized:
            if self._pwm_left:
                self._pwm_left.stop()
            if self._pwm_right:
                self._pwm_right.stop()
            GPIO.cleanup()
            logger.info("[MOTOR] GPIO cleaned up.")
        self._initialized = False

    # ── Core movement commands ────────────────────────────────────

    def forward(self, speed: int = DEFAULT_SPEED) -> None:
        """Drive both wheels forward at the given speed."""
        speed = self._clamp_speed(speed)
        with self._lock:
            self._set_left(forward=True)
            self._set_right(forward=True)
            self._set_pwm(speed, speed)
        logger.debug(f"[MOTOR] Forward speed={speed}")

    def reverse(self, speed: int = DEFAULT_SPEED) -> None:
        """Drive both wheels in reverse at the given speed."""
        speed = self._clamp_speed(speed)
        with self._lock:
            self._set_left(forward=False)
            self._set_right(forward=False)
            self._set_pwm(speed, speed)
        logger.debug(f"[MOTOR] Reverse speed={speed}")

    def steer(self, speed: int = DEFAULT_SPEED, steer: float = 0.0) -> None:
        """
        Differential steering: drive forward with proportional turning.

        Args:
            speed:  Base speed (0-100).
            steer:  Steering factor (-1.0 = full left, 0.0 = straight,
                    +1.0 = full right).

        The inner wheel slows down proportionally:
            steer > 0 (right turn) → right wheel slows
            steer < 0 (left turn)  → left wheel slows
        """
        speed = self._clamp_speed(speed)
        steer = max(-1.0, min(1.0, steer))

        # Unified differential formula (no branching — avoids inversion)
        #   steer > 0 → turn right: left faster, right slower
        #   steer < 0 → turn left:  left slower, right faster
        left_speed = self._clamp_speed(
            int(speed * max(0.0, min(1.0, 1.0 + steer)))
        )
        right_speed = self._clamp_speed(
            int(speed * max(0.0, min(1.0, 1.0 - steer)))
        )

        with self._lock:
            self._set_left(forward=True)
            self._set_right(forward=True)
            self._set_pwm(left_speed, right_speed)
        logger.debug(
            f"[MOTOR] Steer speed={speed} steer={steer:.2f} "
            f"L={left_speed} R={right_speed}"
        )

    def pivot_left(self, speed: int = DEFAULT_SPEED) -> None:
        """Pivot in place: left wheel reverse, right wheel forward."""
        speed = self._clamp_speed(speed)
        with self._lock:
            self._set_left(forward=False)
            self._set_right(forward=True)
            self._set_pwm(speed, speed)
        logger.debug(f"[MOTOR] Pivot LEFT speed={speed}")

    def pivot_right(self, speed: int = DEFAULT_SPEED) -> None:
        """Pivot in place: left wheel forward, right wheel reverse."""
        speed = self._clamp_speed(speed)
        with self._lock:
            self._set_left(forward=True)
            self._set_right(forward=False)
            self._set_pwm(speed, speed)
        logger.debug(f"[MOTOR] Pivot RIGHT speed={speed}")

    def brake(self) -> None:
        """
        Active brake: set IN1=IN2=HIGH with full PWM for 50ms,
        then release to coast. Stops the car immediately.
        """
        with self._lock:
            self._set_brake_pins()
            self._set_pwm(100, 100)

        # Hold brake for 50ms
        time.sleep(0.05)

        with self._lock:
            self._set_pwm(0, 0)
            self._set_coast_pins()
        logger.debug("[MOTOR] Active brake applied")

    def coast(self) -> None:
        """Release motors: PWM=0, all IN pins LOW. Free spinning."""
        with self._lock:
            self._set_pwm(0, 0)
            self._set_coast_pins()
        logger.debug("[MOTOR] Coast (released)")

    # ── Private helpers ───────────────────────────────────────────

    def _set_left(self, forward: bool) -> None:
        """Set left motor direction. Must be called inside lock."""
        if not _HAS_GPIO:
            return
        if forward:
            GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
            GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
        else:
            GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
            GPIO.output(MOTOR_LEFT_IN2, GPIO.HIGH)

    def _set_right(self, forward: bool) -> None:
        """Set right motor direction. Must be called inside lock."""
        if not _HAS_GPIO:
            return
        if forward:
            GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
            GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)
        else:
            GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
            GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH)

    def _set_pwm(self, left: int, right: int) -> None:
        """Set PWM duty cycle for both motors. Must be called inside lock."""
        if not _HAS_GPIO:
            return
        if self._pwm_left:
            self._pwm_left.ChangeDutyCycle(left)
        if self._pwm_right:
            self._pwm_right.ChangeDutyCycle(right)

    def _set_brake_pins(self) -> None:
        """Set both channels to brake mode (IN1=IN2=HIGH)."""
        if not _HAS_GPIO:
            return
        GPIO.output(MOTOR_LEFT_IN1, GPIO.HIGH)
        GPIO.output(MOTOR_LEFT_IN2, GPIO.HIGH)
        GPIO.output(MOTOR_RIGHT_IN1, GPIO.HIGH)
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.HIGH)

    def _set_coast_pins(self) -> None:
        """Set both channels to coast mode (IN1=IN2=LOW)."""
        if not _HAS_GPIO:
            return
        GPIO.output(MOTOR_LEFT_IN1, GPIO.LOW)
        GPIO.output(MOTOR_LEFT_IN2, GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN1, GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN2, GPIO.LOW)

    @staticmethod
    def _clamp_speed(speed: int) -> int:
        """Clamp speed to valid PWM range 0-100."""
        return max(0, min(100, int(speed)))
