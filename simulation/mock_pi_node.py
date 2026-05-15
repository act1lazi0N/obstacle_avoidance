"""
AutoCar — Mock Pi Node (MQTT Simulation)

Simulates the Raspberry Pi node for testing on a PC:
    - Publishes webcam frames to autocar/camera/frame
    - Publishes fake ultrasonic data to autocar/sensor/ultrasonic
    - Subscribes to autocar/command/motor and logs commands
    - Publishes fake FSM state transitions

Usage:
    python -m simulation.mock_pi_node
    python -m simulation.mock_pi_node --camera 0  (webcam index)
    python -m simulation.mock_pi_node --no-camera  (synthetic frames only)
"""

import argparse
import signal
import sys
import time
import threading
import random
import logging
import platform

import cv2
import numpy as np

from shared.config import (
    Topics, CAMERA_WIDTH, CAMERA_HEIGHT,
    JPEG_QUALITY, CAMERA_FPS, ULTRASONIC_PUBLISH_HZ,
)
from shared.mqtt_client import AutoCarMQTT

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_CAMERA_WARMUP_READS = 8
_CAMERA_FAILURE_LIMIT = 10


class MockPiNode:
    """
    Simulates the Pi node for development and testing.

    Can use a real webcam or generate synthetic frames.
    Logs all received motor commands to console.
    """

    def __init__(
        self,
        mqtt_client: AutoCarMQTT,
        camera_index: int = 0,
        use_camera: bool = True,
    ):
        self._mqtt = mqtt_client
        self._camera_index = camera_index
        self._use_camera = use_camera
        self._cap = None
        self._running = False
        self._camera_source = "synthetic" if not use_camera else "opening"
        self._camera_failures = 0
        self._current_state = "idle"
        self._current_speed = 0
        self._current_steer = 0.0

    def start(self) -> None:
        """Initialize camera and start all threads."""
        # Try webcam
        if self._use_camera:
            self._cap = self._open_camera(self._camera_index)
            if self._cap is None:
                logger.warning(
                    f"[MOCK] Cannot open webcam {self._camera_index}. "
                    "Using synthetic frames."
                )
                self._use_camera = False
                self._camera_source = "synthetic"
            else:
                self._camera_source = "webcam"
                logger.info(
                    f"[MOCK] Webcam {self._camera_index} opened and readable."
                )
        else:
            self._camera_source = "synthetic"

        # Subscribe to motor commands
        self._mqtt.subscribe_json(
            Topics.COMMAND_MOTOR, self._on_motor_command
        )
        self._mqtt.subscribe(
            Topics.CONTROL_EMERGENCY_STOP, self._on_emergency_stop
        )

        self._running = True

        # Camera publisher
        threading.Thread(
            target=self._camera_loop, daemon=True
        ).start()

        # Ultrasonic publisher
        threading.Thread(
            target=self._ultrasonic_loop, daemon=True
        ).start()

        logger.info("[MOCK] Mock Pi Node started.")
        self._publish_event(
            "mock_pi_started",
            f"Mock Pi started with camera_source={self._camera_source}",
        )

    def stop(self) -> None:
        self._running = False
        if self._cap:
            self._cap.release()

    def _on_motor_command(self, topic: str, data: dict) -> None:
        """Log received motor commands."""
        action = data.get("action", "unknown")
        speed = data.get("speed", 0)
        steer = data.get("steer", 0.0)

        self._current_state = action
        self._current_speed = speed
        self._current_steer = steer

        # Visual logging
        arrows = {
            "cruise": "⬆️ ",
            "reverse": "⬇️ ",
            "steer": "↗️ " if steer > 0 else "↖️ ",
            "pivot_left": "⤺ ",
            "pivot_right": "⤻ ",
            "brake": "🛑",
            "stop": "⏹️ ",
            "emergency_stop": "🚨",
            "reset": "🔄",
        }
        icon = arrows.get(action, "❓")
        logger.info(
            f"[MOCK] {icon} MOTOR: {action} speed={speed} steer={steer:.2f}"
        )

        # Publish FSM state
        self._publish_fsm_state(action, speed, steer)

    def _on_emergency_stop(self, topic: str, payload: bytes) -> None:
        logger.warning("[MOCK] 🚨 EMERGENCY STOP received!")
        self._current_state = "emergency_stop"
        self._current_speed = 0
        self._publish_fsm_state("emergency_stop", 0, 0.0)

    def _publish_fsm_state(self, state: str, speed: int, steer: float) -> None:
        self._mqtt.publish_json(
            Topics.STATE_FSM,
            {"state": state, "speed": speed, "steer": round(steer, 2)},
        )

    def _open_camera(self, camera_index: int):
        """Open and verify a webcam, preferring DirectShow on Windows."""
        backends = []
        if platform.system() == "Windows":
            backends.extend([cv2.CAP_DSHOW, cv2.CAP_MSMF])
        backends.append(cv2.CAP_ANY)

        for backend in backends:
            cap = cv2.VideoCapture(camera_index, backend)
            if not cap.isOpened():
                cap.release()
                continue

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)

            for _ in range(_CAMERA_WARMUP_READS):
                ret, frame = cap.read()
                if ret and frame is not None:
                    return cap
                time.sleep(0.05)

            cap.release()
        return None

    def _read_camera_frame(self):
        if not self._cap or not self._use_camera:
            self._camera_source = "synthetic"
            return self._synthetic_frame()

        ret, frame = self._cap.read()
        if ret and frame is not None:
            self._camera_failures = 0
            self._camera_source = "webcam"
            return cv2.resize(frame, (CAMERA_WIDTH, CAMERA_HEIGHT))

        self._camera_failures += 1
        logger.warning(
            f"[MOCK] Webcam read failed "
            f"({self._camera_failures}/{_CAMERA_FAILURE_LIMIT})."
        )
        if self._camera_failures >= _CAMERA_FAILURE_LIMIT:
            logger.warning("[MOCK] Webcam unstable. Falling back to synthetic.")
            self._publish_event(
                "mock_camera_fallback",
                "Webcam read failed repeatedly; using synthetic frames",
            )
            self._use_camera = False
            if self._cap:
                self._cap.release()
                self._cap = None
            self._camera_source = "synthetic"

        return self._synthetic_frame()

    def _publish_sensor_state(self, **extra) -> None:
        payload = {
            "camera_status": self._camera_source,
            "source": "mock_pi_node",
            "timestamp": time.time(),
        }
        payload.update(extra)
        self._mqtt.publish_json(Topics.STATE_SENSORS, payload)

    def _publish_event(self, event_type: str, message: str) -> None:
        self._mqtt.publish_json(
            Topics.EVENT,
            {
                "timestamp": time.time(),
                "source": "mock_pi_node",
                "type": event_type,
                "message": message,
            },
            retain=True,
        )

    def _camera_loop(self) -> None:
        """Publish camera frames at configured FPS."""
        interval = 1.0 / CAMERA_FPS
        while self._running:
            try:
                frame = self._read_camera_frame()

                # Overlay state info
                cv2.putText(
                    frame,
                    f"STATE: {self._current_state.upper()}",
                    (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
                )
                cv2.putText(
                    frame,
                    f"SPD: {self._current_speed}  STR: {self._current_steer:.2f}",
                    (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1,
                )

                # Encode and publish
                ok, buf = cv2.imencode(
                    ".jpg", frame,
                    [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY],
                )
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                self._mqtt.publish_bytes(Topics.CAMERA_FRAME, buf.tobytes())
                self._publish_sensor_state()

            except Exception as e:
                logger.error(f"[MOCK] Camera error: {e}")

            time.sleep(interval)

    def _ultrasonic_loop(self) -> None:
        """Publish simulated ultrasonic readings."""
        interval = 1.0 / ULTRASONIC_PUBLISH_HZ
        base_distance = 80.0

        while self._running:
            # Simulate: distance varies slowly with noise
            noise = random.gauss(0, 5)
            distance = max(3.0, base_distance + noise)

            # Occasionally simulate obstacle approach
            if random.random() < 0.02:
                base_distance = random.uniform(5, 30)
            elif base_distance < 50:
                base_distance += 2  # Slowly recover

            self._mqtt.publish_json(
                Topics.SENSOR_ULTRASONIC,
                {"distance_cm": round(distance, 1)},
            )
            self._publish_sensor_state(ultrasonic_cm=round(distance, 1))
            time.sleep(interval)

    @staticmethod
    def _synthetic_frame() -> np.ndarray:
        """Generate a synthetic test frame."""
        frame = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)

        # Gradient background
        for y in range(CAMERA_HEIGHT):
            brightness = int(60 + (y / CAMERA_HEIGHT) * 120)
            frame[y, :] = [brightness, brightness, brightness]

        # "Road" markers
        cv2.line(
            frame, (CAMERA_WIDTH // 3, CAMERA_HEIGHT),
            (CAMERA_WIDTH // 3, CAMERA_HEIGHT // 2),
            (0, 150, 255), 2,
        )
        cv2.line(
            frame, (2 * CAMERA_WIDTH // 3, CAMERA_HEIGHT),
            (2 * CAMERA_WIDTH // 3, CAMERA_HEIGHT // 2),
            (0, 150, 255), 2,
        )

        # Title
        cv2.putText(
            frame, "SIMULATION",
            (80, CAMERA_HEIGHT // 2 - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
        )
        timestamp = time.strftime("%H:%M:%S")
        cv2.putText(
            frame, timestamp,
            (110, CAMERA_HEIGHT // 2 + 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1,
        )

        return frame


def main():
    parser = argparse.ArgumentParser(description="AutoCar Mock Pi Node")
    parser.add_argument(
        "--camera", type=int, default=0,
        help="Webcam index (default: 0)",
    )
    parser.add_argument(
        "--no-camera", action="store_true",
        help="Use synthetic frames (no webcam)",
    )
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("AUTOCAR MOCK PI NODE (Simulation)")
    logger.info("=" * 50)

    mqtt_client = AutoCarMQTT(client_id="mock_pi_node")
    mqtt_client.set_will(Topics.STATUS_PI, "offline")
    try:
        mqtt_client.connect()
    except ConnectionError as e:
        logger.critical(f"MQTT connection failed: {e}")
        sys.exit(1)

    mock = MockPiNode(
        mqtt_client,
        camera_index=args.camera,
        use_camera=not args.no_camera,
    )
    mock.start()

    def cleanup(sig=None, frame=None):
        logger.info("Shutting down Mock Pi Node...")
        mock.stop()
        mqtt_client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    logger.info("[MOCK] Running. Press Ctrl+C to stop.")

    try:
        signal.pause()
    except AttributeError:
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
