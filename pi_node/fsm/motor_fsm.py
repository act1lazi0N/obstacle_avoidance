"""
AutoCar — Motor Finite State Machine

Manages motor states with validated transitions, watchdog timeout,
and safety constraints. Acts as the single authority over motor commands
on the Raspberry Pi.

States:
    IDLE            → Motor off, PWM = 0
    CRUISING        → Both wheels forward, speed parameterized
    REVERSING       → Both wheels reverse
    STEERING_LEFT   → Rẽ trái MỀM: left wheel slower, right faster
    STEERING_RIGHT  → Rẽ phải MỀM: right wheel slower, left faster
    PIVOT_LEFT      → Left reverse, right forward (in-place rotation)
    PIVOT_RIGHT     → Left forward, right reverse (in-place rotation)
    BRAKING         → Active brake (transient → IDLE after 50ms)
    EMERGENCY_STOP  → Brake + lock, only unlockable via explicit reset
"""

import time
import threading
import logging
from enum import Enum, auto
from typing import Optional, Callable

from pi_node.hal.motor import MotorController
from shared.config import WATCHDOG_TIMEOUT, DEFAULT_SPEED

logger = logging.getLogger(__name__)


class MotorState(Enum):
    IDLE = auto()
    CRUISING = auto()
    REVERSING = auto()
    STEERING_LEFT = auto()
    STEERING_RIGHT = auto()
    PIVOT_LEFT = auto()
    PIVOT_RIGHT = auto()
    BRAKING = auto()
    EMERGENCY_STOP = auto()


# Valid transitions table
# Key = current state, Value = set of allowed next states
_TRANSITIONS = {
    MotorState.IDLE: {
        MotorState.CRUISING,
        MotorState.REVERSING,
        MotorState.STEERING_LEFT,
        MotorState.STEERING_RIGHT,
        MotorState.PIVOT_LEFT,
        MotorState.PIVOT_RIGHT,
        MotorState.BRAKING,
        MotorState.EMERGENCY_STOP,
    },
    MotorState.CRUISING: {
        MotorState.STEERING_LEFT,
        MotorState.STEERING_RIGHT,
        MotorState.BRAKING,
        MotorState.EMERGENCY_STOP,
        MotorState.IDLE,
    },
    MotorState.REVERSING: {
        MotorState.BRAKING,
        MotorState.EMERGENCY_STOP,
        MotorState.IDLE,
    },
    MotorState.STEERING_LEFT: {
        MotorState.CRUISING,
        MotorState.STEERING_RIGHT,
        MotorState.BRAKING,
        MotorState.EMERGENCY_STOP,
        MotorState.IDLE,
    },
    MotorState.STEERING_RIGHT: {
        MotorState.CRUISING,
        MotorState.STEERING_LEFT,
        MotorState.BRAKING,
        MotorState.EMERGENCY_STOP,
        MotorState.IDLE,
    },
    MotorState.PIVOT_LEFT: {
        MotorState.BRAKING,
        MotorState.EMERGENCY_STOP,
        MotorState.IDLE,
    },
    MotorState.PIVOT_RIGHT: {
        MotorState.BRAKING,
        MotorState.EMERGENCY_STOP,
        MotorState.IDLE,
    },
    MotorState.BRAKING: {
        MotorState.IDLE,
        MotorState.EMERGENCY_STOP,
    },
    MotorState.EMERGENCY_STOP: {
        MotorState.IDLE,  # Only via explicit reset
    },
}


class MotorFSM:
    """
    Finite State Machine for motor control.

    - Validates all state transitions
    - Enforces watchdog timeout (auto-stop if no command received)
    - EMERGENCY_STOP overrides any state and locks until reset
    - Publishes state changes via callback
    """

    def __init__(
        self,
        motor: MotorController,
        on_state_change: Optional[Callable[[MotorState, int], None]] = None,
    ):
        """
        Args:
            motor:           MotorController instance
            on_state_change: Callback(new_state, speed) called on every
                             state transition. Used to publish via MQTT.
        """
        self._motor = motor
        self._on_state_change = on_state_change
        self._state = MotorState.IDLE
        self._speed = 0
        self._steer = 0.0
        self._lock = threading.Lock()
        self._last_command_time = time.time()
        self._watchdog_running = False
        self._watchdog_thread = None

    @property
    def state(self) -> MotorState:
        return self._state

    @property
    def speed(self) -> int:
        return self._speed

    # ── Public commands ───────────────────────────────────────────

    def cruise(self, speed: int = DEFAULT_SPEED) -> bool:
        """Transition to CRUISING state (forward, given speed)."""
        return self._transition_to(MotorState.CRUISING, speed=speed)

    def reverse(self, speed: int = DEFAULT_SPEED) -> bool:
        """Transition to REVERSING state."""
        # Must brake first if currently cruising
        if self._state == MotorState.CRUISING:
            self.brake()
        return self._transition_to(MotorState.REVERSING, speed=speed)

    def steer_left(self, speed: int = DEFAULT_SPEED, steer: float = -0.5) -> bool:
        """Transition to STEERING_LEFT (differential soft turn)."""
        return self._transition_to(
            MotorState.STEERING_LEFT, speed=speed, steer=steer
        )

    def steer_right(self, speed: int = DEFAULT_SPEED, steer: float = 0.5) -> bool:
        """Transition to STEERING_RIGHT (differential soft turn)."""
        return self._transition_to(
            MotorState.STEERING_RIGHT, speed=speed, steer=steer
        )

    def steer_proportional(self, speed: int = DEFAULT_SPEED, steer: float = 0.0) -> bool:
        """
        Smart steering: auto-selects CRUISING, STEERING_LEFT, or STEERING_RIGHT
        based on steer value.
        """
        if abs(steer) < 0.05:
            return self.cruise(speed)
        elif steer < 0:
            return self.steer_left(speed, steer)
        else:
            return self.steer_right(speed, steer)

    def pivot_left(self, speed: int = DEFAULT_SPEED) -> bool:
        """Transition to PIVOT_LEFT (in-place rotation)."""
        return self._transition_to(MotorState.PIVOT_LEFT, speed=speed)

    def pivot_right(self, speed: int = DEFAULT_SPEED) -> bool:
        """Transition to PIVOT_RIGHT (in-place rotation)."""
        return self._transition_to(MotorState.PIVOT_RIGHT, speed=speed)

    def brake(self) -> bool:
        """Transition to BRAKING → IDLE."""
        ok = self._transition_to(MotorState.BRAKING)
        if ok:
            # Braking is transient — auto-transition to IDLE
            self._transition_to(MotorState.IDLE)
        return ok

    def stop(self) -> bool:
        """Soft stop: coast to IDLE."""
        return self._transition_to(MotorState.IDLE)

    def emergency_stop(self) -> bool:
        """
        EMERGENCY STOP: immediately brake and lock.
        Overrides any current state. Only reset() can unlock.
        """
        with self._lock:
            old = self._state
            self._state = MotorState.EMERGENCY_STOP
            self._speed = 0
            self._steer = 0.0
            self._motor.brake()
            self._notify_state_change()
            logger.warning(f"[FSM] EMERGENCY STOP (was {old.name})")
        return True

    def reset(self) -> bool:
        """Reset from EMERGENCY_STOP to IDLE. Only valid transition out of E-STOP."""
        with self._lock:
            if self._state != MotorState.EMERGENCY_STOP:
                logger.warning("[FSM] reset() called but not in EMERGENCY_STOP")
                return False
            self._state = MotorState.IDLE
            self._speed = 0
            self._steer = 0.0
            self._motor.coast()
            self._notify_state_change()
            logger.info("[FSM] Reset from EMERGENCY_STOP → IDLE")
        return True

    # ── Watchdog ──────────────────────────────────────────────────

    def start_watchdog(self) -> None:
        """Start the watchdog thread that auto-stops on command timeout."""
        if self._watchdog_running:
            return
        self._watchdog_running = True
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True
        )
        self._watchdog_thread.start()
        logger.info(f"[FSM] Watchdog started (timeout: {WATCHDOG_TIMEOUT}s)")

    def stop_watchdog(self) -> None:
        """Stop the watchdog thread."""
        self._watchdog_running = False

    def _watchdog_loop(self) -> None:
        """Background loop: stop motors if no command received recently."""
        was_stopped = False
        while self._watchdog_running:
            elapsed = time.time() - self._last_command_time
            if elapsed > WATCHDOG_TIMEOUT:
                if not was_stopped and self._state not in (
                    MotorState.IDLE, MotorState.EMERGENCY_STOP
                ):
                    logger.warning(
                        f"[FSM] WATCHDOG: No command in {WATCHDOG_TIMEOUT}s. "
                        "Stopping."
                    )
                    self.stop()
                    was_stopped = True
            else:
                was_stopped = False
            time.sleep(0.5)

    # ── State info ────────────────────────────────────────────────

    def get_state_dict(self) -> dict:
        """Return current state as a JSON-serializable dict."""
        return {
            "state": self._state.name.lower(),
            "speed": self._speed,
            "steer": round(self._steer, 2),
        }

    # ── Internal ──────────────────────────────────────────────────

    def _transition_to(
        self,
        target: MotorState,
        speed: int = 0,
        steer: float = 0.0,
    ) -> bool:
        """
        Attempt a state transition. Returns True if successful.
        Applies the motor command corresponding to the target state.
        """
        with self._lock:
            # Emergency stop is always locked
            if self._state == MotorState.EMERGENCY_STOP and target != MotorState.IDLE:
                logger.warning(
                    f"[FSM] Cannot transition from EMERGENCY_STOP to "
                    f"{target.name}. Use reset() first."
                )
                return False

            # Validate transition
            allowed = _TRANSITIONS.get(self._state, set())
            if target not in allowed and target != self._state:
                logger.warning(
                    f"[FSM] Invalid transition: {self._state.name} → "
                    f"{target.name}"
                )
                return False

            old = self._state
            self._state = target
            self._speed = speed
            self._steer = steer
            self._last_command_time = time.time()

            # Execute motor command
            self._execute_state(target, speed, steer)

            if old != target:
                self._notify_state_change()
                logger.debug(
                    f"[FSM] {old.name} → {target.name} "
                    f"(speed={speed}, steer={steer:.2f})"
                )

        return True

    def _execute_state(
        self, state: MotorState, speed: int, steer: float
    ) -> None:
        """Apply motor commands for the given state."""
        if state == MotorState.IDLE:
            self._motor.coast()
        elif state == MotorState.CRUISING:
            self._motor.forward(speed)
        elif state == MotorState.REVERSING:
            self._motor.reverse(speed)
        elif state in (MotorState.STEERING_LEFT, MotorState.STEERING_RIGHT):
            self._motor.steer(speed, steer)
        elif state == MotorState.PIVOT_LEFT:
            self._motor.pivot_left(speed)
        elif state == MotorState.PIVOT_RIGHT:
            self._motor.pivot_right(speed)
        elif state == MotorState.BRAKING:
            self._motor.brake()
        elif state == MotorState.EMERGENCY_STOP:
            self._motor.brake()

    def _notify_state_change(self) -> None:
        """Call the state change callback if registered."""
        if self._on_state_change:
            try:
                self._on_state_change(self._state, self._speed)
            except Exception as e:
                logger.error(f"[FSM] State change callback error: {e}")
