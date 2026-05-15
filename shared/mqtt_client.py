"""
AutoCar MQTT client wrapper.

Provides a small, consistent API over paho-mqtt for the Pi node,
simulation node, AI brain, and dashboard.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from shared.config import MQTT_BROKER_IP, MQTT_BROKER_PORT, MQTT_KEEPALIVE

logger = logging.getLogger(__name__)

RawMessageHandler = Callable[[str, bytes], None]
JsonMessageHandler = Callable[[str, dict[str, Any]], None]


class AutoCarMQTT:
    """Thin paho-mqtt wrapper used by all AutoCar nodes."""

    def __init__(
        self,
        client_id: str,
        broker_ip: str = MQTT_BROKER_IP,
        broker_port: int = MQTT_BROKER_PORT,
        keepalive: int = MQTT_KEEPALIVE,
    ):
        self._client_id = client_id
        self._broker_ip = broker_ip
        self._broker_port = broker_port
        self._keepalive = keepalive
        self._connected = threading.Event()
        self._connect_error: str | None = None
        self._will_topic: str | None = None
        self._subscriptions: dict[str, RawMessageHandler] = {}
        self._lock = threading.Lock()

        self._client = self._create_client(client_id)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @staticmethod
    def _create_client(client_id: str) -> mqtt.Client:
        try:
            return mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
            )
        except (AttributeError, TypeError):
            return mqtt.Client(client_id=client_id)

    def set_will(self, topic: str, payload: str | bytes, qos: int = 1) -> None:
        """Configure MQTT last will before connecting."""
        self._will_topic = topic
        self._client.will_set(topic, payload=payload, qos=qos, retain=True)

    def connect(self, timeout: float = 5.0) -> None:
        """Connect to the broker and start the network loop."""
        self._connected.clear()
        self._connect_error = None

        try:
            result = self._client.connect(
                self._broker_ip,
                self._broker_port,
                self._keepalive,
            )
        except OSError as exc:
            raise ConnectionError(
                f"Could not connect to MQTT broker "
                f"{self._broker_ip}:{self._broker_port}: {exc}"
            ) from exc

        if result != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT connect failed with code {result}")

        self._client.loop_start()
        if not self._connected.wait(timeout):
            self.disconnect()
            detail = self._connect_error or "timeout waiting for CONNACK"
            raise ConnectionError(
                f"MQTT connect failed for {self._broker_ip}:"
                f"{self._broker_port}: {detail}"
            )

        if self._will_topic:
            self.publish_bytes(self._will_topic, b"online", qos=1, retain=True)

        logger.info(
            "[MQTT] %s connected to %s:%s",
            self._client_id,
            self._broker_ip,
            self._broker_port,
        )

    def disconnect(self) -> None:
        """Disconnect from the broker and stop the network loop."""
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()
            self._connected.clear()

    def subscribe(
        self,
        topic: str,
        callback: RawMessageHandler,
        qos: int = 0,
    ) -> None:
        """Subscribe to a raw MQTT topic."""
        with self._lock:
            self._subscriptions[topic] = callback
        result, mid = self._client.subscribe(topic, qos=qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(
                f"Subscribe failed for {topic} with code {result}"
            )
        logger.info("[MQTT] subscribed to %s (mid=%s)", topic, mid)

    def subscribe_json(
        self,
        topic: str,
        callback: JsonMessageHandler,
        qos: int = 0,
    ) -> None:
        """Subscribe to a JSON topic and pass decoded dictionaries."""

        def _json_handler(message_topic: str, payload: bytes) -> None:
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.warning(
                    "[MQTT] Dropping invalid JSON on %s: %s",
                    message_topic,
                    exc,
                )
                return

            if not isinstance(data, dict):
                logger.warning(
                    "[MQTT] Dropping non-object JSON on %s", message_topic
                )
                return

            callback(message_topic, data)

        self.subscribe(topic, _json_handler, qos=qos)

    def publish_json(
        self,
        topic: str,
        data: dict[str, Any],
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        """Publish a dictionary as JSON."""
        payload = json.dumps(data, separators=(",", ":"))
        self._client.publish(topic, payload=payload, qos=qos, retain=retain)

    def publish_bytes(
        self,
        topic: str,
        payload: bytes,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        """Publish raw bytes."""
        self._client.publish(topic, payload=payload, qos=qos, retain=retain)

    def publish_empty(
        self,
        topic: str,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        """Publish an empty payload."""
        self.publish_bytes(topic, b"", qos=qos, retain=retain)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if self._is_success(reason_code):
            self._connected.set()
            return

        self._connect_error = str(reason_code)
        logger.error("[MQTT] connect failed: %s", reason_code)

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags=None,
        reason_code=None,
        properties=None,
    ):
        self._connected.clear()
        if reason_code and not self._is_success(reason_code):
            logger.warning("[MQTT] disconnected: %s", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        with self._lock:
            callback = self._subscriptions.get(msg.topic)

        if callback is None:
            logger.debug("[MQTT] no handler for topic %s", msg.topic)
            return

        try:
            callback(msg.topic, msg.payload)
        except Exception:
            logger.exception("[MQTT] message handler failed for %s", msg.topic)

    @staticmethod
    def _is_success(reason_code) -> bool:
        if reason_code == 0:
            return True
        if str(reason_code).lower() in {"0", "success", "normal disconnection"}:
            return True
        value = getattr(reason_code, "value", None)
        return value == 0
