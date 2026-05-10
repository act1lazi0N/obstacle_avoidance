"""
AutoCar — Pi Node MQTT Bridge

Bridges MQTT messages to/from local hardware:
    - Subscribes to motor commands → drives FSM
    - Subscribes to emergency stop → triggers E-STOP
    - Publishes camera frames periodically
    - Publishes ultrasonic readings periodically
    - Publishes FSM state on change
"""

import json
import time
import threading
import logging

from shared.config import Topics, CAMERA_FPS, ULTRASONIC_PUBLISH_HZ
from shared.mqtt_client import AutoCarMQTT
from pi_node.hal.camera import PiCamera
from pi_node.hal.ultrasonic import UltrasonicSensor
from pi_node.fsm.motor_fsm import MotorFSM, MotorState

logger = logging.getLogger(__name__)


class PiMQTTBridge:
    """
    MQTT bridge for the Raspberry Pi node.

    Connects hardware (HAL) and FSM to the MQTT message bus.
    """

    def __init__(
        self,
        mqtt_client: AutoCarMQTT,
        fsm: MotorFSM,
        camera: PiCamera,
        ultrasonic: UltrasonicSensor,
    ):
        self._mqtt = mqtt_client
        self._fsm = fsm
        self._camera = camera
        self._ultrasonic = ultrasonic
        self._running = False

        # Register FSM state change callback
        self._fsm._on_state_change = self._on_fsm_state_change

    def start(self) -> None:
        """Subscribe to topics and start publisher threads."""
        # Subscribe to incoming commands
        self._mqtt.subscribe_json(
            Topics.COMMAND_MOTOR, self._handle_motor_command
        )
        self._mqtt.subscribe(
            Topics.CONTROL_EMERGENCY_STOP, self._handle_emergency_stop
        )

        self._running = True

        # Start camera frame publisher
        cam_thread = threading.Thread(
            target=self._camera_publish_loop, daemon=True
        )
        cam_thread.start()
        logger.info(f"[BRIDGE] Camera publisher started ({CAMERA_FPS} FPS)")

        # Start ultrasonic publisher
        sonic_thread = threading.Thread(
            target=self._ultrasonic_publish_loop, daemon=True
        )
        sonic_thread.start()
        logger.info(
            f"[BRIDGE] Ultrasonic publisher started ({ULTRASONIC_PUBLISH_HZ} Hz)"
        )

    def stop(self) -> None:
        """Stop all publisher threads."""
        self._running = False

    # ── Incoming command handlers ─────────────────────────────────

    def _handle_motor_command(self, topic: str, data: dict) -> None:
        """
        Handle motor commands from AI brain.

        Expected payload:
            {"action": "cruise"|"reverse"|"steer"|"pivot_left"|"pivot_right"|"stop"|"brake",
             "speed": 0-100,
             "steer": -1.0 to 1.0}
        """
        action = data.get("action", "stop")
        speed = int(data.get("speed", 0))
        steer = float(data.get("steer", 0.0))

        if action == "cruise":
            self._fsm.cruise(speed)
        elif action == "reverse":
            self._fsm.reverse(speed)
        elif action == "steer":
            self._fsm.steer_proportional(speed, steer)
        elif action == "pivot_left":
            self._fsm.pivot_left(speed)
        elif action == "pivot_right":
            self._fsm.pivot_right(speed)
        elif action == "brake":
            self._fsm.brake()
        elif action == "stop":
            self._fsm.stop()
        elif action == "emergency_stop":
            self._fsm.emergency_stop()
        elif action == "reset":
            self._fsm.reset()
        else:
            logger.warning(f"[BRIDGE] Unknown motor action: {action}")

    def _handle_emergency_stop(self, topic: str, payload: bytes) -> None:
        """Handle emergency stop signal (any payload, including empty)."""
        logger.warning("[BRIDGE] EMERGENCY STOP received via MQTT!")
        self._fsm.emergency_stop()

    # ── Outgoing publishers ───────────────────────────────────────

    def _camera_publish_loop(self) -> None:
        """Periodically capture and publish camera frames via MQTT."""
        interval = 1.0 / CAMERA_FPS
        while self._running:
            try:
                jpeg_bytes = self._camera.capture_jpeg()
                if jpeg_bytes:
                    self._mqtt.publish_bytes(
                        Topics.CAMERA_FRAME, jpeg_bytes, qos=0
                    )
            except Exception as e:
                logger.error(f"[BRIDGE] Camera publish error: {e}")
            time.sleep(interval)

    def _ultrasonic_publish_loop(self) -> None:
        """Periodically measure and publish ultrasonic distance."""
        interval = 1.0 / ULTRASONIC_PUBLISH_HZ
        while self._running:
            try:
                distance = self._ultrasonic.measure_distance()
                self._mqtt.publish_json(
                    Topics.SENSOR_ULTRASONIC,
                    {"distance_cm": distance},
                    qos=0,
                )
            except Exception as e:
                logger.error(f"[BRIDGE] Ultrasonic publish error: {e}")
            time.sleep(interval)

    def _on_fsm_state_change(self, new_state: MotorState, speed: int) -> None:
        """Publish FSM state changes to MQTT."""
        self._mqtt.publish_json(
            Topics.STATE_FSM,
            self._fsm.get_state_dict(),
            qos=0,
        )
