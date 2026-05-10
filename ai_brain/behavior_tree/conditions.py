"""
AutoCar — Behavior Tree Conditions

Condition nodes that read from the blackboard and return
SUCCESS (condition met) or FAILURE (condition not met).

These are pure checks — they never issue motor commands.
"""

import py_trees
import logging

from ai_brain.behavior_tree.blackboard_keys import BBKeys
from shared.config import (
    DANGER_LEVEL_CAUTION,
    DANGER_LEVEL_DANGER,
    CONFIRM_FRAMES,
    CLEAR_FRAMES,
    MAX_CAMERA_FAILURES,
)

logger = logging.getLogger(__name__)


class IsAIEnabled(py_trees.behaviour.Behaviour):
    """Check if AI is enabled. Fails → whole tree skipped."""

    def __init__(self, name="IsAIEnabled"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.AI_ENABLED, access=py_trees.common.Access.READ
        )

    def update(self):
        try:
            enabled = self.blackboard.get(BBKeys.AI_ENABLED)
            return (
                py_trees.common.Status.SUCCESS
                if enabled
                else py_trees.common.Status.FAILURE
            )
        except KeyError:
            return py_trees.common.Status.SUCCESS  # Default: AI on


class IsFrameAvailable(py_trees.behaviour.Behaviour):
    """Check if a new camera frame is available."""

    def __init__(self, name="IsFrameAvailable"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.FRAME_AVAILABLE, access=py_trees.common.Access.READ
        )

    def update(self):
        try:
            available = self.blackboard.get(BBKeys.FRAME_AVAILABLE)
            return (
                py_trees.common.Status.SUCCESS
                if available
                else py_trees.common.Status.FAILURE
            )
        except KeyError:
            return py_trees.common.Status.FAILURE


class IsCameraBlind(py_trees.behaviour.Behaviour):
    """
    Check if camera is failing (too dark, no frame, etc.).
    Uses a counter for hysteresis — must fail MAX_CAMERA_FAILURES times.
    """

    def __init__(self, name="IsCameraBlind"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.FUSED_PERCEPTION, access=py_trees.common.Access.READ
        )
        self.blackboard.register_key(
            key=BBKeys.CAMERA_FAIL_COUNTER, access=py_trees.common.Access.WRITE
        )

    def update(self):
        try:
            perception = self.blackboard.get(BBKeys.FUSED_PERCEPTION)
        except KeyError:
            return py_trees.common.Status.FAILURE

        try:
            counter = self.blackboard.get(BBKeys.CAMERA_FAIL_COUNTER)
        except KeyError:
            counter = 0

        if perception.is_blind:
            counter += 1
        else:
            counter = 0

        self.blackboard.set(BBKeys.CAMERA_FAIL_COUNTER, counter)

        if counter >= MAX_CAMERA_FAILURES:
            logger.warning(f"[BT] Camera blind for {counter} frames!")
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE


class IsCollisionImminent(py_trees.behaviour.Behaviour):
    """Check if TTC or ultrasonic indicates collision is imminent."""

    def __init__(self, name="IsCollisionImminent"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.FUSED_PERCEPTION, access=py_trees.common.Access.READ
        )

    def update(self):
        try:
            perception = self.blackboard.get(BBKeys.FUSED_PERCEPTION)
            if perception.is_collision_imminent or perception.danger_level >= 0.95:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except KeyError:
            return py_trees.common.Status.FAILURE


class IsDeadEnd(py_trees.behaviour.Behaviour):
    """Check if the car is in a dead-end (blocked, must escape)."""

    def __init__(self, name="IsDeadEnd"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.FUSED_PERCEPTION, access=py_trees.common.Access.READ
        )
        self.blackboard.register_key(
            key=BBKeys.DANGER_COUNTER, access=py_trees.common.Access.WRITE
        )

    def update(self):
        try:
            perception = self.blackboard.get(BBKeys.FUSED_PERCEPTION)
        except KeyError:
            return py_trees.common.Status.FAILURE

        try:
            counter = self.blackboard.get(BBKeys.DANGER_COUNTER)
        except KeyError:
            counter = 0

        if perception.is_dead_end:
            counter += 1
        else:
            counter = 0

        self.blackboard.set(BBKeys.DANGER_COUNTER, counter)

        if counter >= CONFIRM_FRAMES:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE


class IsDanger(py_trees.behaviour.Behaviour):
    """Check if danger level is above active avoidance threshold."""

    def __init__(self, name="IsDanger"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.FUSED_PERCEPTION, access=py_trees.common.Access.READ
        )

    def update(self):
        try:
            perception = self.blackboard.get(BBKeys.FUSED_PERCEPTION)
            if perception.danger_level >= DANGER_LEVEL_DANGER:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except KeyError:
            return py_trees.common.Status.FAILURE


class IsCaution(py_trees.behaviour.Behaviour):
    """
    Check if danger level is in the caution zone (slow down but don't avoid).
    Between DANGER_LEVEL_CAUTION and DANGER_LEVEL_DANGER.
    """

    def __init__(self, name="IsCaution"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.FUSED_PERCEPTION, access=py_trees.common.Access.READ
        )

    def update(self):
        try:
            perception = self.blackboard.get(BBKeys.FUSED_PERCEPTION)
            if DANGER_LEVEL_CAUTION <= perception.danger_level < DANGER_LEVEL_DANGER:
                return py_trees.common.Status.SUCCESS
            return py_trees.common.Status.FAILURE
        except KeyError:
            return py_trees.common.Status.FAILURE


class IsEscapeActive(py_trees.behaviour.Behaviour):
    """Check if an escape maneuver is currently running."""

    def __init__(self, name="IsEscapeActive"):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client()
        self.blackboard.register_key(
            key=BBKeys.ESCAPE_ACTIVE, access=py_trees.common.Access.READ
        )

    def update(self):
        try:
            active = self.blackboard.get(BBKeys.ESCAPE_ACTIVE)
            return (
                py_trees.common.Status.SUCCESS
                if active
                else py_trees.common.Status.FAILURE
            )
        except KeyError:
            return py_trees.common.Status.FAILURE
