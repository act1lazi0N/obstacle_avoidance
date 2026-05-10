"""
AutoCar — Pi Node Entry Point

Initializes all hardware (HAL), starts the FSM and watchdog,
connects to MQTT, and begins publishing sensor data.

Usage (on Raspberry Pi):
    python -m pi_node.main

Usage (on PC for testing — motors will be mock):
    python -m pi_node.main
"""

import signal
import sys
import logging

from shared.config import WATCHDOG_TIMEOUT, Topics
from shared.mqtt_client import AutoCarMQTT
from pi_node.hal.motor import MotorController
from pi_node.hal.ultrasonic import UltrasonicSensor
from pi_node.hal.camera import PiCamera
from pi_node.fsm.motor_fsm import MotorFSM
from pi_node.mqtt_bridge import PiMQTTBridge

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    # ── Initialize Hardware ───────────────────────────────────────
    logger.info("=" * 50)
    logger.info("AUTOCAR PI NODE — Initializing...")
    logger.info("=" * 50)

    motor = MotorController()
    ultrasonic = UltrasonicSensor()
    camera = PiCamera()

    try:
        motor.setup()
    except Exception as e:
        logger.critical(f"Motor setup failed: {e}")
        sys.exit(1)

    try:
        ultrasonic.setup()
    except Exception as e:
        logger.warning(f"Ultrasonic setup failed: {e}. Continuing without it.")

    try:
        camera.setup()
    except Exception as e:
        logger.critical(f"Camera setup failed: {e}")
        motor.cleanup()
        sys.exit(1)

    # ── Initialize FSM ────────────────────────────────────────────
    fsm = MotorFSM(motor)
    fsm.start_watchdog()

    # ── Initialize MQTT with LWT ──────────────────────────────────
    mqtt_client = AutoCarMQTT(client_id="pi_node")

    # LWT: if Pi disconnects unexpectedly, broker sends "offline"
    mqtt_client.set_will(Topics.STATUS_PI, "offline")

    try:
        mqtt_client.connect()
    except ConnectionError as e:
        logger.critical(f"MQTT connection failed: {e}")
        camera.cleanup()
        motor.cleanup()
        sys.exit(1)

    # ── Initialize Bridge ─────────────────────────────────────────
    bridge = PiMQTTBridge(mqtt_client, fsm, camera, ultrasonic)
    bridge.start()

    # ── Signal handlers ───────────────────────────────────────────
    def cleanup(sig=None, frame=None):
        logger.info("Shutting down Pi Node...")
        bridge.stop()
        fsm.stop_watchdog()
        fsm.stop()
        mqtt_client.disconnect()
        camera.cleanup()
        motor.cleanup()
        logger.info("Pi Node stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # ── Run ───────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("PI NODE RUNNING")
    logger.info(f"  MQTT: {mqtt_client._broker_ip}:{mqtt_client._broker_port}")
    logger.info(f"  Watchdog timeout: {WATCHDOG_TIMEOUT}s")
    logger.info("  Press Ctrl+C to stop")
    logger.info("=" * 50)

    # Keep main thread alive
    try:
        signal.pause()
    except AttributeError:
        # signal.pause() not available on Windows
        import time
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
