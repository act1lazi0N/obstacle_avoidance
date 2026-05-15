"""
AutoCar dashboard MQTT listener.

Keeps the Flask dashboard's in-memory state synchronized with MQTT updates
from the mock/real Pi node and AI brain.
"""

from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from typing import Any

from shared.config import Topics
from shared.mqtt_client import AutoCarMQTT

logger = logging.getLogger(__name__)

_CONNECTED_WINDOW_SECONDS = 5.0


class DashboardState:
    """Thread-safe state container for `/api/state`."""

    def __init__(self):
        self._lock = threading.Lock()
        self._fsm: dict[str, Any] = {
            "state": "idle",
            "speed": 0,
            "steer": 0.0,
        }
        self._brain: dict[str, Any] = {
            "danger_level": 0.0,
            "obstacle_region": "none",
            "is_dead_end": False,
            "ultrasonic_cm": 999.0,
            "camera_obstacles": 0,
            "motor_command": {"action": "waiting", "speed": 0, "steer": 0.0},
            "frame_count": 0,
            "selected_behavior": "waiting",
            "decision_reason": "waiting for AI state",
            "camera_status": "unknown",
        }
        self._sensors: dict[str, Any] = {
            "ultrasonic_cm": 999.0,
            "camera_status": "unknown",
            "frame_age_ms": None,
        }
        self._perception: dict[str, Any] = {
            "obstacle_count": 0,
            "max_area": 0,
            "total_area": 0,
            "dominant_region": "center",
            "brightness": None,
            "is_blind": False,
        }
        self._fusion: dict[str, Any] = {
            "danger_level": 0.0,
            "is_dead_end": False,
            "is_collision_imminent": False,
            "obstacle_region": "none",
            "steer_suggestion": 0.0,
            "free_direction": "center",
            "area_expansion_rate": 0.0,
        }
        self._decision: dict[str, Any] = {
            "selected_behavior": "waiting",
            "reason": "waiting for decision state",
            "motor_command": {"action": "waiting", "speed": 0, "steer": 0.0},
            "tick_ms": None,
        }
        self._safety: dict[str, Any] = {
            "system_fault": False,
            "pi_online": False,
            "camera_status": "unknown",
            "emergency_stop": False,
            "reason": "waiting",
        }
        self._latest_event: dict[str, Any] = {
            "type": "none",
            "message": "no events yet",
            "source": "dashboard",
        }
        self._pi_status = "unknown"
        self._last_pi_update = 0.0
        self._last_ai_update = 0.0
        self._message_times: dict[str, float] = {}

    def update_fsm(self, topic: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._touch(topic)
            self._fsm.update(
                {
                    "state": str(data.get("state", self._fsm["state"])),
                    "speed": int(data.get("speed", self._fsm["speed"])),
                    "steer": float(data.get("steer", self._fsm["steer"])),
                }
            )
            self._safety["emergency_stop"] = (
                self._fsm["state"] == "emergency_stop"
                or bool(self._safety.get("emergency_stop", False))
            )
            self._last_pi_update = time.time()

    def update_brain(self, topic: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._touch(topic)
            self._brain.update(data)
            self._brain["danger_level"] = float(
                self._brain.get("danger_level", 0.0)
            )
            self._brain["ultrasonic_cm"] = float(
                self._brain.get("ultrasonic_cm", 999.0)
            )
            self._brain["camera_obstacles"] = int(
                self._brain.get("camera_obstacles", 0)
            )
            self._decision["selected_behavior"] = self._brain.get(
                "selected_behavior",
                self._decision["selected_behavior"],
            )
            self._decision["reason"] = self._brain.get(
                "decision_reason",
                self._decision["reason"],
            )
            self._decision["motor_command"] = self._brain.get(
                "motor_command",
                self._decision["motor_command"],
            )
            self._sensors["camera_status"] = self._brain.get(
                "camera_status",
                self._sensors["camera_status"],
            )
            self._last_ai_update = time.time()

    def update_sensors(self, topic: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._touch(topic)
            self._sensors.update(data)
            if "ultrasonic_cm" in data:
                self._brain["ultrasonic_cm"] = float(data["ultrasonic_cm"])
            elif "distance_cm" in data:
                self._sensors["ultrasonic_cm"] = float(data["distance_cm"])
                self._brain["ultrasonic_cm"] = float(data["distance_cm"])
            self._last_pi_update = time.time()

    def update_perception(self, topic: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._touch(topic)
            self._perception.update(data)
            self._brain["camera_obstacles"] = int(
                data.get("obstacle_count", self._brain["camera_obstacles"])
            )

    def update_fusion(self, topic: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._touch(topic)
            self._fusion.update(data)
            self._brain["danger_level"] = float(
                data.get("danger_level", self._brain["danger_level"])
            )

    def update_decision(self, topic: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._touch(topic)
            self._decision.update(data)
            self._brain["selected_behavior"] = self._decision.get(
                "selected_behavior",
                self._brain["selected_behavior"],
            )
            self._brain["decision_reason"] = self._decision.get(
                "reason",
                self._brain["decision_reason"],
            )
            self._brain["motor_command"] = self._decision.get(
                "motor_command",
                self._brain["motor_command"],
            )
            self._last_ai_update = time.time()

    def update_safety(self, topic: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._touch(topic)
            self._safety.update(data)
            self._safety["emergency_stop"] = bool(
                self._safety.get("emergency_stop", False)
            )

    def update_event(self, topic: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._touch(topic)
            self._latest_event = data

    def update_pi_status(self, topic: str, status: str) -> None:
        with self._lock:
            self._touch(topic)
            self._pi_status = status.strip().lower()
            self._last_pi_update = time.time()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            pi_recent = now - self._last_pi_update <= _CONNECTED_WINDOW_SECONDS
            ai_recent = now - self._last_ai_update <= _CONNECTED_WINDOW_SECONDS
            pi_connected = self._pi_status == "online" or (
                self._pi_status != "offline" and pi_recent
            )
            message_age = {
                topic: round(now - last_seen, 2)
                for topic, last_seen in self._message_times.items()
            }
            latest_age = (
                round(now - max(self._message_times.values()), 2)
                if self._message_times else None
            )

            return {
                "system": {
                    "pi_connected": pi_connected,
                    "ai_connected": ai_recent,
                    "pi_status": self._pi_status,
                    "latest_mqtt_age_s": latest_age,
                    "message_age_s": message_age,
                },
                "fsm": deepcopy(self._fsm),
                "brain": deepcopy(self._brain),
                "sensors": deepcopy(self._sensors),
                "perception": deepcopy(self._perception),
                "fusion": deepcopy(self._fusion),
                "decision": deepcopy(self._decision),
                "safety": deepcopy(self._safety),
                "event": deepcopy(self._latest_event),
            }

    def _touch(self, topic: str) -> None:
        self._message_times[topic] = time.time()


class DashboardMQTTListener:
    """Subscribes to MQTT topics and updates DashboardState."""

    def __init__(self, mqtt_client: AutoCarMQTT, state: DashboardState):
        self._mqtt = mqtt_client
        self._state = state

    def start(self) -> None:
        self._mqtt.subscribe_json(Topics.STATE_FSM, self._handle_fsm)
        self._mqtt.subscribe_json(Topics.STATE_BRAIN, self._handle_brain)
        self._mqtt.subscribe_json(Topics.SENSOR_ULTRASONIC, self._handle_sensors)
        self._mqtt.subscribe_json(Topics.STATE_SENSORS, self._handle_sensors)
        self._mqtt.subscribe_json(Topics.STATE_PERCEPTION, self._handle_perception)
        self._mqtt.subscribe_json(Topics.STATE_FUSION, self._handle_fusion)
        self._mqtt.subscribe_json(Topics.STATE_DECISION, self._handle_decision)
        self._mqtt.subscribe_json(Topics.STATE_SAFETY, self._handle_safety)
        self._mqtt.subscribe_json(Topics.EVENT, self._handle_event)
        self._mqtt.subscribe(Topics.STATUS_PI, self._handle_pi_status)
        logger.info("[DASHBOARD] MQTT listener started")

    def _handle_fsm(self, topic: str, data: dict[str, Any]) -> None:
        self._state.update_fsm(topic, data)

    def _handle_brain(self, topic: str, data: dict[str, Any]) -> None:
        self._state.update_brain(topic, data)

    def _handle_sensors(self, topic: str, data: dict[str, Any]) -> None:
        self._state.update_sensors(topic, data)

    def _handle_perception(self, topic: str, data: dict[str, Any]) -> None:
        self._state.update_perception(topic, data)

    def _handle_fusion(self, topic: str, data: dict[str, Any]) -> None:
        self._state.update_fusion(topic, data)

    def _handle_decision(self, topic: str, data: dict[str, Any]) -> None:
        self._state.update_decision(topic, data)

    def _handle_safety(self, topic: str, data: dict[str, Any]) -> None:
        self._state.update_safety(topic, data)

    def _handle_event(self, topic: str, data: dict[str, Any]) -> None:
        self._state.update_event(topic, data)

    def _handle_pi_status(self, topic: str, payload: bytes) -> None:
        status = payload.decode("utf-8", errors="replace")
        self._state.update_pi_status(topic, status)
