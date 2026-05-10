"""
AutoCar — Behavior Tree Builder

Constructs the complete behavior tree with priority-based architecture.

Tree Structure (Selector = try children in priority order):
    Root (Selector)
    ├─ P0: Camera Fail-Safe     [Sequence: IsCameraBlind → CameraFailSafe]
    ├─ P1: Emergency Brake      [Sequence: IsCollisionImminent → EmergencyBrake]
    ├─ P2: Dead-End Escape      [Sequence(memory=True): IsDeadEnd → EscapeManeuver]
    │      memory=True ensures that once IsDeadEnd triggers, the escape
    │      Sequence runs to completion WITHOUT re-checking IsDeadEnd.
    ├─ P3: Active Avoidance     [Sequence: IsDanger → ProportionalAvoid]
    ├─ P4: Cautious Cruise      [Sequence: IsCaution → CautiousCruise]
    └─ P5: Free Cruise          [FreeCruise (always succeeds)]

The tree is ticked once per perception frame (~10Hz).
Higher priorities preempt lower ones.

NOTE: Previous P2 (IsEscapeActive + separate EscapeManeuver) was removed
because it caused the escape to interrupt mid-sequence: when the car
reversed away from a dead-end, IsDeadEnd returned FAILURE, terminating
P3's Sequence, and P2's separate EscapeManeuver instance lost state.
With memory=True on P3, once the Sequence starts, IsDeadEnd is NOT
re-evaluated until the EscapeManeuver completes or is preempted by P0/P1.
"""

import logging
import py_trees

from ai_brain.behavior_tree.conditions import (
    IsAIEnabled,
    IsFrameAvailable,
    IsCameraBlind,
    IsCollisionImminent,
    IsDeadEnd,
    IsDanger,
    IsCaution,
)
from ai_brain.behavior_tree.actions import (
    FreeCruise,
    CautiousCruise,
    ProportionalAvoid,
    EmergencyBrake,
    CameraFailSafe,
    EscapeManeuver,
)

logger = logging.getLogger(__name__)


def build_tree() -> py_trees.trees.BehaviourTree:
    """
    Build and return the complete behavior tree.

    Returns:
        py_trees.trees.BehaviourTree ready to be ticked.
    """

    # ── Priority 0: Camera Fail-Safe ─────────────────────────────
    p0_camera_failsafe = py_trees.composites.Sequence(
        name="P0_CameraFailSafe",
        memory=False,
        children=[
            IsCameraBlind(),
            CameraFailSafe(),
        ],
    )

    # ── Priority 1: Emergency Brake (AEB) ─────────────────────────
    p1_emergency_brake = py_trees.composites.Sequence(
        name="P1_EmergencyBrake",
        memory=True,  # memory=True so EmergencyBrake can RUNNING
        children=[
            IsCollisionImminent(),
            EmergencyBrake(),
        ],
    )

    # ── Priority 2: Dead-End Escape ──────────────────────────────
    #   memory=True → once IsDeadEnd returns SUCCESS, it is NOT
    #   re-checked on subsequent ticks. The EscapeManeuver runs
    #   its full reverse→stop→pivot→verify cycle uninterrupted.
    #   Only a higher-priority node (P0/P1) can preempt.
    p2_dead_end_escape = py_trees.composites.Sequence(
        name="P2_DeadEndEscape",
        memory=True,
        children=[
            IsDeadEnd(),
            EscapeManeuver("EscapeManeuver"),
        ],
    )

    # ── Priority 3: Active Avoidance ─────────────────────────────
    p3_active_avoid = py_trees.composites.Sequence(
        name="P3_ActiveAvoidance",
        memory=False,
        children=[
            IsDanger(),
            ProportionalAvoid(),
        ],
    )

    # ── Priority 4: Cautious Cruise ──────────────────────────────
    p4_cautious_cruise = py_trees.composites.Sequence(
        name="P4_CautiousCruise",
        memory=False,
        children=[
            IsCaution(),
            CautiousCruise(),
        ],
    )

    # ── Priority 5: Free Cruise (fallback — always succeeds) ─────
    p5_free_cruise = FreeCruise()

    # ── Root: Priority Selector ───────────────────────────────────
    root_selector = py_trees.composites.Selector(
        name="DrivingPriorities",
        memory=False,
        children=[
            p0_camera_failsafe,
            p1_emergency_brake,
            p2_dead_end_escape,
            p3_active_avoid,
            p4_cautious_cruise,
            p5_free_cruise,
        ],
    )

    # ── Guard: AI enabled + frame available ───────────────────────
    guarded_tree = py_trees.composites.Sequence(
        name="AutoCarBrain",
        memory=False,
        children=[
            IsAIEnabled(),
            IsFrameAvailable(),
            root_selector,
        ],
    )

    tree = py_trees.trees.BehaviourTree(root=guarded_tree)

    logger.info("[BT] Behavior tree built:")
    logger.info(py_trees.display.ascii_tree(tree.root))

    return tree
