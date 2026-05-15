"""
AutoCar — AI Brain MQTT Bridge

Connects the AI perception pipeline and behavior tree to MQTT:
    - Subscribes to camera frames → runs detection → fuses with ultrasonic
    - Updates blackboard with fused perception
    - Ticks behavior tree
    - Reads motor command from blackboard → publishes to Pi
    - Publishes brain state for dashboard
"""

import time
import threading
import logging
from typing import Any

import cv2
import numpy as np
import py_trees

from shared.config import Topics
from shared.mqtt_client import AutoCarMQTT
from ai_brain.perception.detector import ObstacleDetector
from ai_brain.perception.sensor_fusion import SensorFusion, FusedPerception
from ai_brain.behavior_tree.blackboard_keys import BBKeys

logger = logging.getLogger(__name__)

# Max seconds without a frame before AI considers Pi disconnected
_FRAME_TIMEOUT = 5.0


class AIBrainBridge:
    """
    MQTT bridge for the AI Brain node.

    Receives camera frames and ultrasonic data from Pi,
    runs the perception pipeline and behavior tree,
    and publishes motor commands back to the Pi.
    """

    def __init__(
        self,
        mqtt_client: AutoCarMQTT,
        detector: ObstacleDetector,
        fusion: SensorFusion,
        tree: py_trees.trees.BehaviourTree,
    ):
        self._mqtt = mqtt_client
        self._detector = detector
        self._fusion = fusion
        self._tree = tree
        self._running = False

        # Latest data (thread-safe via locks)
        self._latest_frame: bytes = b""
        self._latest_ultrasonic: float = 999.0
        self._frame_lock = threading.Lock()
        self._ultrasonic_lock = threading.Lock()
        self._frame_count = 0
        self._last_frame_time = time.time()
        self._pi_online = True
        self._system_fault = False
        self._camera_status = "waiting"
        self._last_decision: dict[str, Any] = {
            "selected_behavior": "waiting",
            "reason": "waiting for first frame",
        }

        # Blackboard reference
        self._blackboard = py_trees.blackboard.Client(name="AIBridge")
        self._blackboard.register_key(
            key=BBKeys.FUSED_PERCEPTION, access=py_trees.common.Access.WRITE
        )
        self._blackboard.register_key(
            key=BBKeys.RAW_FRAME, access=py_trees.common.Access.WRITE
        )
        self._blackboard.register_key(
            key=BBKeys.FRAME_AVAILABLE, access=py_trees.common.Access.WRITE
        )
        self._blackboard.register_key(
            key=BBKeys.ULTRASONIC_CM, access=py_trees.common.Access.WRITE
        )
        self._blackboard.register_key(
            key=BBKeys.AI_ENABLED, access=py_trees.common.Access.WRITE
        )
        self._blackboard.register_key(
            key=BBKeys.MOTOR_COMMAND, access=py_trees.common.Access.READ
        )

        # Default values
        self._blackboard.set(BBKeys.AI_ENABLED, True)
        self._blackboard.set(BBKeys.FRAME_AVAILABLE, False)

    def start(self) -> None:
        """Subscribe to topics and start processing loop."""
        # Subscribe to sensor data from Pi
        self._mqtt.subscribe(
            Topics.CAMERA_FRAME, self._handle_camera_frame
        )
        self._mqtt.subscribe_json(
            Topics.SENSOR_ULTRASONIC, self._handle_ultrasonic
        )
        self._mqtt.subscribe(
            Topics.CONTROL_AI_TOGGLE, self._handle_ai_toggle
        )

        # Subscribe to Pi online/offline status (LWT)
        self._mqtt.subscribe(
            Topics.STATUS_PI, self._handle_pi_status
        )

        self._running = True

        # Start the main processing loop
        process_thread = threading.Thread(
            target=self._process_loop, daemon=True
        )
        process_thread.start()
        logger.info("[AI_BRIDGE] Processing loop started")
        self._publish_event("ai_bridge_started", "AI bridge processing loop started")

    def stop(self) -> None:
        """Stop the processing loop."""
        self._running = False

    # ── Incoming data handlers ────────────────────────────────────

    def _handle_camera_frame(self, topic: str, payload: bytes) -> None:
        """Receive JPEG frame from Pi."""
        with self._frame_lock:
            self._latest_frame = payload
            self._last_frame_time = time.time()

    def _handle_ultrasonic(self, topic: str, data: dict) -> None:
        """Receive ultrasonic distance from Pi."""
        with self._ultrasonic_lock:
            self._latest_ultrasonic = float(data.get("distance_cm", 999.0))

    def _handle_pi_status(self, topic: str, payload: bytes) -> None:
        """Handle Pi online/offline status from LWT."""
        status = payload.decode("utf-8", errors="replace").strip()
        was_online = self._pi_online
        self._pi_online = (status == "online")

        if self._pi_online and not was_online:
            logger.info("[AI_BRIDGE] ✅ Pi is ONLINE")
            self._system_fault = False
            self._publish_event("pi_online", "Pi status changed to online")
        elif not self._pi_online and was_online:
            logger.critical(
                "[AI_BRIDGE] 🚨 Pi went OFFLINE — setting system_fault=True"
            )
            self._system_fault = True
            self._blackboard.set(BBKeys.AI_ENABLED, False)
            self._publish_safety("pi_offline")
            self._publish_event("pi_offline", "Pi status changed to offline")

    def _handle_ai_toggle(self, topic: str, payload: bytes) -> None:
        """Toggle AI on/off from dashboard."""
        try:
            import json
            data = json.loads(payload.decode("utf-8"))
            enabled = data.get("enabled", True)
            self._blackboard.set(BBKeys.AI_ENABLED, enabled)
            logger.info(f"[AI_BRIDGE] AI {'ENABLED' if enabled else 'DISABLED'}")
        except Exception:
            # Toggle on empty payload
            try:
                current = self._blackboard.get(BBKeys.AI_ENABLED)
                self._blackboard.set(BBKeys.AI_ENABLED, not current)
                logger.info(f"[AI_BRIDGE] AI toggled to {not current}")
            except KeyError:
                pass

    # ── Main processing loop ─────────────────────────────────────

    def _process_loop(self) -> None:
        """
        Main AI loop:
        1. Decode latest frame
        2. Run detection + fusion
        3. Update blackboard
        4. Tick behavior tree
        5. Read motor command → publish
        """
        while self._running:
            start_time = time.time()

            try:
                # 1. Check system fault (Pi offline)
                if self._system_fault:
                    self._publish_safety("system_fault")
                    time.sleep(0.5)
                    continue

                # Check frame timeout (stale data detection)
                with self._frame_lock:
                    frame_age = time.time() - self._last_frame_time
                if frame_age > _FRAME_TIMEOUT and self._pi_online:
                    logger.warning(
                        f"[AI_BRIDGE] No frame for {frame_age:.1f}s "
                        "— possible Pi disconnect"
                    )
                    self._system_fault = True
                    self._blackboard.set(BBKeys.AI_ENABLED, False)
                    self._camera_status = "stale"
                    self._publish_safety("frame_timeout")
                    self._publish_event(
                        "frame_timeout",
                        f"No camera frame for {frame_age:.1f}s",
                    )
                    continue

                # 2. Get latest frame
                with self._frame_lock:
                    jpeg_bytes = self._latest_frame
                    self._latest_frame = b""

                if not jpeg_bytes:
                    self._blackboard.set(BBKeys.FRAME_AVAILABLE, False)
                    self._camera_status = "waiting"
                    time.sleep(0.05)
                    continue

                # Decode JPEG → BGR
                np_arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is None:
                    self._blackboard.set(BBKeys.FRAME_AVAILABLE, False)
                    self._camera_status = "decode_failed"
                    time.sleep(0.05)
                    continue
                self._camera_status = "ok"

                # 2. Run detection
                detection = self._detector.detect(frame)

                # 3. Get ultrasonic data
                with self._ultrasonic_lock:
                    ultrasonic_cm = self._latest_ultrasonic

                # 4. Sensor fusion
                perception = self._fusion.fuse(
                    detection, frame, ultrasonic_cm
                )

                # 5. Update blackboard
                self._blackboard.set(BBKeys.FUSED_PERCEPTION, perception)
                self._blackboard.set(BBKeys.RAW_FRAME, frame)
                self._blackboard.set(BBKeys.FRAME_AVAILABLE, True)
                self._blackboard.set(BBKeys.ULTRASONIC_CM, ultrasonic_cm)

                # 6. Tick behavior tree
                self._tree.tick()

                # 7. Read motor command and publish
                motor_cmd = {"action": "unknown", "speed": 0, "steer": 0.0}
                try:
                    motor_cmd = self._blackboard.get(BBKeys.MOTOR_COMMAND)
                    if motor_cmd:
                        self._mqtt.publish_json(
                            Topics.COMMAND_MOTOR, motor_cmd, qos=0
                        )
                except KeyError:
                    pass

                # 8. Publish brain state (throttled)
                self._frame_count += 1
                self._last_decision = self._build_decision(perception, motor_cmd)
                if self._frame_count % 5 == 0:
                    self._publish_brain_state(perception)
                    self._publish_observability(
                        detection,
                        perception,
                        motor_cmd,
                        frame_age,
                        elapsed=time.time() - start_time,
                    )

            except Exception as e:
                logger.error(f"[AI_BRIDGE] Process loop error: {e}", exc_info=True)

            # Throttle to ~10 Hz
            elapsed = time.time() - start_time
            sleep_time = max(0.01, 0.1 - elapsed)
            time.sleep(sleep_time)

    def _publish_brain_state(self, perception: FusedPerception) -> None:
        """Publish AI brain state for dashboard."""
        try:
            motor_cmd = self._blackboard.get(BBKeys.MOTOR_COMMAND)
        except KeyError:
            motor_cmd = {"action": "unknown"}

        state = {
            "danger_level": perception.danger_level,
            "obstacle_region": perception.obstacle_region,
            "is_dead_end": perception.is_dead_end,
            "ultrasonic_cm": perception.ultrasonic_cm,
            "camera_obstacles": perception.camera_obstacle_count,
            "motor_command": motor_cmd,
            "frame_count": self._frame_count,
            "selected_behavior": self._last_decision["selected_behavior"],
            "decision_reason": self._last_decision["reason"],
            "camera_status": self._camera_status,
        }
        self._mqtt.publish_json(Topics.STATE_BRAIN, state, qos=0)

    def _publish_observability(
        self,
        detection,
        perception: FusedPerception,
        motor_cmd: dict[str, Any],
        frame_age: float,
        elapsed: float,
    ) -> None:
        """Publish lightweight research telemetry without changing decisions."""
        timestamp = time.time()
        self._mqtt.publish_json(
            Topics.STATE_SENSORS,
            {
                "timestamp": timestamp,
                "ultrasonic_cm": perception.ultrasonic_cm,
                "camera_status": self._camera_status,
                "frame_age_ms": round(frame_age * 1000, 1),
            },
            qos=0,
        )
        self._mqtt.publish_json(
            Topics.STATE_PERCEPTION,
            {
                "timestamp": timestamp,
                "camera_status": self._camera_status,
                "obstacle_count": detection.obstacle_count,
                "max_area": detection.max_area,
                "total_area": detection.total_area,
                "dominant_region": detection.dominant_region,
                "brightness": perception.brightness,
                "is_blind": perception.is_blind,
            },
            qos=0,
        )
        self._mqtt.publish_json(
            Topics.STATE_FUSION,
            {
                "timestamp": timestamp,
                "danger_level": perception.danger_level,
                "is_dead_end": perception.is_dead_end,
                "is_collision_imminent": perception.is_collision_imminent,
                "obstacle_region": perception.obstacle_region,
                "steer_suggestion": perception.steer_suggestion,
                "free_direction": perception.free_direction,
                "area_expansion_rate": perception.area_expansion_rate,
            },
            qos=0,
        )
        self._mqtt.publish_json(
            Topics.STATE_DECISION,
            {
                "timestamp": timestamp,
                "selected_behavior": self._last_decision["selected_behavior"],
                "reason": self._last_decision["reason"],
                "motor_command": motor_cmd,
                "tick_ms": round(elapsed * 1000, 1),
            },
            qos=0,
        )
        self._publish_safety("ok")

    def _publish_safety(self, reason: str) -> None:
        """Publish coarse safety/fault state for research visibility."""
        self._mqtt.publish_json(
            Topics.STATE_SAFETY,
            {
                "timestamp": time.time(),
                "system_fault": self._system_fault,
                "pi_online": self._pi_online,
                "camera_status": self._camera_status,
                "emergency_stop": reason in {"pi_offline", "frame_timeout"},
                "reason": reason,
            },
            qos=0,
        )

    def _publish_event(self, event_type: str, message: str) -> None:
        """Publish notable lifecycle/fault events."""
        self._mqtt.publish_json(
            Topics.EVENT,
            {
                "timestamp": time.time(),
                "source": "ai_brain",
                "type": event_type,
                "message": message,
            },
            qos=0,
            retain=True,
        )

    @staticmethod
    def _build_decision(
        perception: FusedPerception,
        motor_cmd: dict[str, Any],
    ) -> dict[str, str]:
        """Derive a human-readable decision label from existing outputs."""
        action = motor_cmd.get("action", "unknown")
        if perception.is_blind:
            return {
                "selected_behavior": "camera_failsafe",
                "reason": "camera blind or unavailable",
            }
        if perception.is_collision_imminent or perception.danger_level >= 0.95:
            return {
                "selected_behavior": "emergency_brake",
                "reason": "collision imminent",
            }
        if perception.is_dead_end:
            return {
                "selected_behavior": "dead_end_escape",
                "reason": "dead-end condition detected",
            }
        if action == "steer":
            return {
                "selected_behavior": "active_avoidance",
                "reason": f"danger in {perception.obstacle_region}",
            }
        if perception.danger_level >= 0.2:
            return {
                "selected_behavior": "cautious_cruise",
                "reason": f"danger level {perception.danger_level:.2f}",
            }
        return {
            "selected_behavior": "free_cruise",
            "reason": "clear path",
        }
