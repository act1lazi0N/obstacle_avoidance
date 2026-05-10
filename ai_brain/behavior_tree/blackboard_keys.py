"""
AutoCar — Behavior Tree Blackboard Key Registry

Central registry for all blackboard keys used in the behavior tree.
This ensures consistent naming and prevents typos across conditions/actions.
"""


class BBKeys:
    """Namespace for all Blackboard variable names."""

    # ── Perception Data (written by MQTT bridge, read by BT) ─────
    FUSED_PERCEPTION = "fused_perception"   # FusedPerception dataclass
    RAW_FRAME = "raw_frame"                 # np.ndarray (BGR)
    FRAME_AVAILABLE = "frame_available"     # bool — new frame ready
    ULTRASONIC_CM = "ultrasonic_cm"         # float — latest distance

    # ── AI Toggle ─────────────────────────────────────────────────
    AI_ENABLED = "ai_enabled"               # bool — AI on/off

    # ── Decision Counters (managed by BT conditions) ─────────────
    CLEAR_COUNTER = "clear_counter"         # int — consecutive clear frames
    DANGER_COUNTER = "danger_counter"       # int — consecutive danger frames
    CAMERA_FAIL_COUNTER = "camera_fail_counter"  # int — consecutive failures

    # ── Escape Maneuver State ────────────────────────────────────
    ESCAPE_ACTIVE = "escape_active"         # bool — escape sequence running
    ESCAPE_PHASE = "escape_phase"           # str — "reverse"|"pivot"|"verify"
    ESCAPE_START_TIME = "escape_start_time" # float — time.time()

    # ── Motor Command Output (written by BT, read by MQTT bridge)
    MOTOR_COMMAND = "motor_command"         # dict — {"action", "speed", "steer"}
