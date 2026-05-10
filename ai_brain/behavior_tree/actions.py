"""
AutoCar — Behavior Tree Actions

Action nodes that write motor commands to the blackboard.
The MQTT bridge reads these and publishes to the Pi.

IMPORTANT: Actions write to MOTOR_COMMAND on the blackboard.
They do NOT directly publish MQTT — that's the bridge's job.
"""

import time
import logging

import py_trees

from ai_brain.behavior_tree.blackboard_keys import BBKeys
from shared.config import (
    DEFAULT_SPEED,
    CAUTIOUS_SPEED_MAX,
    CAUTIOUS_SPEED_MIN,
    DANGER_LEVEL_CAUTION,
    DANGER_LEVEL_DANGER,
    ESCAPE_REVERSE_DURATION,
    ESCAPE_PIVOT_DURATION,
    ESCAPE_STOP_DURATION,
    AEB_COOLDOWN,
)

logger = logging.getLogger(__name__)


def _set_motor_command(blackboard, action: str, speed: int = 0, steer: float = 0.0):
    """Helper to write a motor command to the blackboard."""
    blackboard.set(BBKeys.MOTOR_COMMAND, {
        "action": action,
        "speed": int(speed),
        "steer": round(steer, 3),
    })


class FreeCruise(py_trees.behaviour.Behaviour):
    """
    Priority 6 (lowest): No obstacles → full speed ahead.
    Resets all danger counters.
    """

    def __init__(self, name="FreeCruise"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.MOTOR_COMMAND, access=py_trees.common.Access.WRITE
        )
        self.blackboard.register_key(
            key=BBKeys.CLEAR_COUNTER, access=py_trees.common.Access.WRITE
        )
        self.blackboard.register_key(
            key=BBKeys.DANGER_COUNTER, access=py_trees.common.Access.WRITE
        )

    def update(self):
        _set_motor_command(self.blackboard, "cruise", DEFAULT_SPEED)
        self.blackboard.set(BBKeys.CLEAR_COUNTER, 0)
        self.blackboard.set(BBKeys.DANGER_COUNTER, 0)
        return py_trees.common.Status.SUCCESS


class CautiousCruise(py_trees.behaviour.Behaviour):
    """
    Priority 5: Obstacles detected but not dangerous.
    Speed decreases linearly with danger level.
    """

    def __init__(self, name="CautiousCruise"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.FUSED_PERCEPTION, access=py_trees.common.Access.READ
        )
        self.blackboard.register_key(
            key=BBKeys.MOTOR_COMMAND, access=py_trees.common.Access.WRITE
        )

    def update(self):
        try:
            perception = self.blackboard.get(BBKeys.FUSED_PERCEPTION)
        except KeyError:
            return py_trees.common.Status.FAILURE

        # Linear speed interpolation
        danger_range = DANGER_LEVEL_DANGER - DANGER_LEVEL_CAUTION
        normalized = (perception.danger_level - DANGER_LEVEL_CAUTION) / danger_range
        normalized = max(0.0, min(1.0, normalized))

        speed = int(
            CAUTIOUS_SPEED_MAX - normalized * (CAUTIOUS_SPEED_MAX - CAUTIOUS_SPEED_MIN)
        )

        _set_motor_command(self.blackboard, "cruise", speed)
        logger.debug(
            f"[BT] CautiousCruise: danger={perception.danger_level:.2f} "
            f"speed={speed}"
        )
        return py_trees.common.Status.SUCCESS


class ProportionalAvoid(py_trees.behaviour.Behaviour):
    """
    Priority 4: Active obstacle avoidance with proportional steering.
    Steers away from detected obstacle using differential drive.
    Speed is reduced proportionally to danger level.
    """

    def __init__(self, name="ProportionalAvoid"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.FUSED_PERCEPTION, access=py_trees.common.Access.READ
        )
        self.blackboard.register_key(
            key=BBKeys.MOTOR_COMMAND, access=py_trees.common.Access.WRITE
        )

    def update(self):
        try:
            perception = self.blackboard.get(BBKeys.FUSED_PERCEPTION)
        except KeyError:
            return py_trees.common.Status.FAILURE

        # Speed decreases as danger increases
        speed = max(30, int(CAUTIOUS_SPEED_MIN * (1.0 - perception.danger_level * 0.5)))

        # Use steer suggestion from sensor fusion
        steer = perception.steer_suggestion

        _set_motor_command(self.blackboard, "steer", speed, steer)
        logger.info(
            f"[BT] ProportionalAvoid: steer={steer:.2f} speed={speed} "
            f"region={perception.obstacle_region}"
        )
        return py_trees.common.Status.SUCCESS


class EmergencyBrake(py_trees.behaviour.Behaviour):
    """
    Priority 1: Emergency brake — collision imminent.
    Brakes and waits for AEB cooldown before tree continues.
    """

    def __init__(self, name="EmergencyBrake"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.MOTOR_COMMAND, access=py_trees.common.Access.WRITE
        )
        self._brake_time = 0

    def initialise(self):
        _set_motor_command(self.blackboard, "brake")
        self._brake_time = time.time()
        logger.warning("[BT] EMERGENCY BRAKE!")

    def update(self):
        if time.time() - self._brake_time < AEB_COOLDOWN:
            return py_trees.common.Status.RUNNING
        return py_trees.common.Status.SUCCESS


class CameraFailSafe(py_trees.behaviour.Behaviour):
    """
    Priority 0: Camera failure — stop immediately.
    """

    def __init__(self, name="CameraFailSafe"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.MOTOR_COMMAND, access=py_trees.common.Access.WRITE
        )

    def update(self):
        _set_motor_command(self.blackboard, "stop")
        logger.warning("[BT] Camera blind! Stopping.")
        return py_trees.common.Status.SUCCESS


class EscapeManeuver(py_trees.behaviour.Behaviour):
    """
    Priority 2: Dead-end recovery — multi-phase escape.

    Phase 1: Reverse for ESCAPE_REVERSE_DURATION
    Phase 2: Short stop (ESCAPE_STOP_DURATION)
    Phase 3: Pivot toward free direction for ESCAPE_PIVOT_DURATION
    Phase 4: Verify escape (check if danger cleared)

    Returns RUNNING during escape, SUCCESS when complete.
    """

    def __init__(self, name="EscapeManeuver"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.MOTOR_COMMAND, access=py_trees.common.Access.WRITE
        )
        self.blackboard.register_key(
            key=BBKeys.FUSED_PERCEPTION, access=py_trees.common.Access.READ
        )
        self.blackboard.register_key(
            key=BBKeys.ESCAPE_ACTIVE, access=py_trees.common.Access.WRITE
        )
        self.blackboard.register_key(
            key=BBKeys.ESCAPE_PHASE, access=py_trees.common.Access.WRITE
        )
        self.blackboard.register_key(
            key=BBKeys.ESCAPE_START_TIME, access=py_trees.common.Access.WRITE
        )

        self._phase = "idle"
        self._phase_start = 0
        self._pivot_direction = "left"

    def initialise(self):
        """Start the escape sequence."""
        self._phase = "reverse"
        self._phase_start = time.time()

        # Determine pivot direction from perception
        try:
            perception = self.blackboard.get(BBKeys.FUSED_PERCEPTION)
            self._pivot_direction = perception.free_direction
        except KeyError:
            self._pivot_direction = "left"  # Default

        self.blackboard.set(BBKeys.ESCAPE_ACTIVE, True)
        self.blackboard.set(BBKeys.ESCAPE_PHASE, "reverse")
        self.blackboard.set(BBKeys.ESCAPE_START_TIME, time.time())

        logger.warning(
            f"[BT] ESCAPE START: pivot toward {self._pivot_direction}"
        )

    def update(self):
        elapsed = time.time() - self._phase_start

        if self._phase == "reverse":
            _set_motor_command(self.blackboard, "reverse", 50)
            if elapsed >= ESCAPE_REVERSE_DURATION:
                self._advance_phase("stop")
            return py_trees.common.Status.RUNNING

        elif self._phase == "stop":
            _set_motor_command(self.blackboard, "brake")
            if elapsed >= ESCAPE_STOP_DURATION:
                self._advance_phase("pivot")
            return py_trees.common.Status.RUNNING

        elif self._phase == "pivot":
            if self._pivot_direction == "left":
                _set_motor_command(self.blackboard, "pivot_left", 60)
            else:
                _set_motor_command(self.blackboard, "pivot_right", 60)
            if elapsed >= ESCAPE_PIVOT_DURATION:
                self._advance_phase("verify")
            return py_trees.common.Status.RUNNING

        elif self._phase == "verify":
            # Check if we escaped
            try:
                perception = self.blackboard.get(BBKeys.FUSED_PERCEPTION)
                if not perception.is_dead_end:
                    self._finish()
                    return py_trees.common.Status.SUCCESS
            except KeyError:
                pass

            # Still stuck? Wait a bit then complete anyway
            if elapsed >= 1.0:
                self._finish()
                return py_trees.common.Status.SUCCESS

            _set_motor_command(self.blackboard, "stop")
            return py_trees.common.Status.RUNNING

        return py_trees.common.Status.SUCCESS

    def terminate(self, new_status):
        """Clean up if tree interrupts escape."""
        if new_status == py_trees.common.Status.INVALID:
            self._finish()

    def _advance_phase(self, next_phase: str):
        self._phase = next_phase
        self._phase_start = time.time()
        self.blackboard.set(BBKeys.ESCAPE_PHASE, next_phase)
        logger.info(f"[BT] Escape phase: {next_phase}")

    def _finish(self):
        self._phase = "idle"
        self.blackboard.set(BBKeys.ESCAPE_ACTIVE, False)
        self.blackboard.set(BBKeys.ESCAPE_PHASE, "idle")
        logger.info("[BT] Escape maneuver COMPLETE")
