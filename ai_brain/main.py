"""
AutoCar — AI Brain Entry Point

Initializes YOLOv5 detector, sensor fusion, behavior tree,
connects to MQTT, and starts the AI processing loop.

Usage (on Laptop/PC):
    python -m ai_brain.main
    python -m ai_brain.main --model path/to/custom_model.pt
"""

import argparse
import signal
import sys
import logging

from shared.mqtt_client import AutoCarMQTT
from ai_brain.perception.detector import ObstacleDetector
from ai_brain.perception.sensor_fusion import SensorFusion
from ai_brain.behavior_tree.tree_builder import build_tree
from ai_brain.mqtt_bridge import AIBrainBridge

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="AutoCar AI Brain Node")
    parser.add_argument(
        "--model",
        default="yolov5s.pt",
        help="Path to YOLOv5 model weights (default: yolov5s.pt)",
    )
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("AUTOCAR AI BRAIN — Initializing...")
    logger.info("=" * 50)

    # ── Initialize Perception ─────────────────────────────────────
    detector = ObstacleDetector(model_path=args.model)
    try:
        detector.setup()
    except Exception as e:
        logger.warning(
            "YOLOv5 model failed to load; continuing with empty detections: %s",
            e,
        )

    fusion = SensorFusion()

    # ── Initialize Behavior Tree ──────────────────────────────────
    tree = build_tree()

    # ── Initialize MQTT ───────────────────────────────────────────
    mqtt_client = AutoCarMQTT(client_id="ai_brain")
    try:
        mqtt_client.connect()
    except ConnectionError as e:
        logger.critical(f"MQTT connection failed: {e}")
        sys.exit(1)

    # ── Initialize Bridge ─────────────────────────────────────────
    bridge = AIBrainBridge(mqtt_client, detector, fusion, tree)
    bridge.start()

    # ── Signal handlers ───────────────────────────────────────────
    def cleanup(sig=None, frame=None):
        logger.info("Shutting down AI Brain...")
        bridge.stop()
        mqtt_client.disconnect()
        logger.info("AI Brain stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # ── Run ───────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("AI BRAIN RUNNING")
    logger.info(f"  Model: {args.model}")
    logger.info(f"  MQTT: {mqtt_client._broker_ip}:{mqtt_client._broker_port}")
    logger.info("  Press Ctrl+C to stop")
    logger.info("=" * 50)

    # Keep main thread alive
    try:
        signal.pause()
    except AttributeError:
        import time
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
