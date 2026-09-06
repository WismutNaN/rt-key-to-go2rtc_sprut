"""MQTT adapter that exposes access points as momentary SprutHub switches."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from rtkey_gateway.domain import AccessBinding
from rtkey_gateway.errors import TransportError


_MQTT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class _MqttClient(Protocol):
    on_connect: Callable[..., None] | None
    on_disconnect: Callable[..., None] | None
    on_message: Callable[..., None] | None

    def username_pw_set(self, username: str, password: str | None = None) -> None: ...

    def will_set(
        self, topic: str, payload: str, qos: int = 0, retain: bool = False
    ) -> None: ...

    def reconnect_delay_set(self, min_delay: int, max_delay: int) -> None: ...

    def connect_async(self, host: str, port: int, keepalive: int) -> Any: ...

    def loop_start(self) -> Any: ...

    def loop_stop(self) -> Any: ...

    def disconnect(self) -> Any: ...

    def subscribe(self, topic: str, qos: int = 0) -> Any: ...

    def publish(
        self,
        topic: str,
        payload: str | bytes | None = None,
        qos: int = 0,
        retain: bool = False,
    ) -> Any: ...


class MqttAccessEvents:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        topic_prefix: str = "rtkey",
        client_id: str = "rtkey-gateway",
        keepalive: int = 60,
        pulse_seconds: float = 2.0,
        client_factory: Callable[[], _MqttClient] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self._password = password
        self.topic_prefix = topic_prefix.rstrip("/")
        self.client_id = client_id
        self.keepalive = keepalive
        self.pulse_seconds = pulse_seconds
        self._client_factory = client_factory
        self.log = logger or logging.getLogger(__name__)
        self._client: _MqttClient | None = None
        self._command_handler: Callable[[str], bool] | None = None
        self._bindings: tuple[AccessBinding, ...] = ()
        self._connected = False
        self._lock = threading.RLock()
        self._timers: set[threading.Timer] = set()
        self._seen_messages: dict[tuple[str, int], float] = {}

    def _default_client(self) -> _MqttClient:
        try:
            from paho.mqtt import client as mqtt
        except ImportError as exc:
            raise TransportError("paho-mqtt is not installed") from exc
        return mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )

    @staticmethod
    def _reason_failed(reason_code: object) -> bool:
        if bool(getattr(reason_code, "is_failure", False)):
            return True
        try:
            return int(reason_code) != 0
        except (TypeError, ValueError):
            return str(reason_code).lower() not in {"success", "0"}

    def start(self, command_handler: Callable[[str], bool]) -> None:
        with self._lock:
            if self._client is not None:
                return
            client = (
                self._client_factory()
                if self._client_factory is not None
                else self._default_client()
            )
            self._client = client
            self._command_handler = command_handler
            try:
                client.on_connect = self._on_connect
                client.on_disconnect = self._on_disconnect
                client.on_message = self._on_message
                client.username_pw_set(self.username, self._password)
                client.will_set(
                    f"{self.topic_prefix}/bridge/availability",
                    "offline",
                    qos=1,
                    retain=True,
                )
                client.reconnect_delay_set(1, 60)
                client.connect_async(self.host, self.port, self.keepalive)
                client.loop_start()
            except Exception as exc:
                self._client = None
                self._command_handler = None
                raise TransportError("Could not start MQTT client") from exc

    def stop(self) -> None:
        with self._lock:
            client = self._client
            if client is None:
                return
            timers = tuple(self._timers)
            self._timers.clear()
            self._connected = False
        for timer in timers:
            timer.cancel()
        try:
            try:
                client.publish(
                    f"{self.topic_prefix}/bridge/availability",
                    "offline",
                    qos=1,
                    retain=True,
                )
                client.disconnect()
            finally:
                client.loop_stop()
        except Exception as exc:
            self.log.warning("MQTT client did not stop cleanly: %s", type(exc).__name__)
        finally:
            with self._lock:
                self._client = None
                self._command_handler = None

    def _on_connect(
        self,
        client: _MqttClient,
        _userdata: object,
        _flags: object,
        reason_code: object,
        _properties: object,
    ) -> None:
        if self._reason_failed(reason_code):
            self.log.error("MQTT broker rejected the connection: %s", reason_code)
            return
        with self._lock:
            self._connected = True
            bindings = self._bindings
        client.subscribe(f"{self.topic_prefix}/access/+/set", qos=1)
        self.log.info("Connected to MQTT broker at %s:%d", self.host, self.port)
        self._publish(
            f"{self.topic_prefix}/bridge/availability", "online", retain=True
        )
        self._publish_catalog_now(bindings)

    def _on_disconnect(
        self,
        _client: _MqttClient,
        _userdata: object,
        _flags: object,
        reason_code: object,
        _properties: object,
    ) -> None:
        with self._lock:
            self._connected = False
        if self._reason_failed(reason_code):
            self.log.warning("MQTT connection was lost: %s", reason_code)

    def _on_message(
        self, _client: _MqttClient, _userdata: object, message: object
    ) -> None:
        if bool(getattr(message, "retain", False)):
            self.log.warning("Ignored retained access command")
            return
        topic = str(getattr(message, "topic", ""))
        prefix = f"{self.topic_prefix}/access/"
        if not topic.startswith(prefix) or not topic.endswith("/set"):
            return
        mqtt_key = topic[len(prefix) : -len("/set")]
        if not _MQTT_KEY_RE.fullmatch(mqtt_key):
            self.log.warning("Ignored malformed access command topic")
            return
        try:
            payload = bytes(getattr(message, "payload", b"")).decode(
                "ascii", errors="strict"
            )
        except (TypeError, UnicodeDecodeError):
            self.publish_rejected(mqtt_key, "invalid_payload")
            return
        if payload.strip().upper() not in {"ON", "1", "TRUE", "OPEN"}:
            return
        message_id = getattr(message, "mid", None)
        if isinstance(message_id, int):
            now = time.monotonic()
            message_key = (topic, message_id)
            with self._lock:
                self._seen_messages = {
                    key: seen_at
                    for key, seen_at in self._seen_messages.items()
                    if now - seen_at < 600
                }
                duplicate = bool(getattr(message, "dup", False)) and (
                    message_key in self._seen_messages
                )
                self._seen_messages[message_key] = now
            if duplicate:
                self.publish_rejected(mqtt_key, "duplicate")
                return
        handler = self._command_handler
        if handler is not None:
            handler(mqtt_key)

    def _publish(
        self, topic: str, payload: str, *, retain: bool = False, qos: int = 1
    ) -> None:
        with self._lock:
            client = self._client
            connected = self._connected
        if client is None or not connected:
            return
        try:
            result = client.publish(topic, payload, qos=qos, retain=retain)
        except Exception as exc:
            self.log.warning(
                "MQTT publish failed for %s (%s)", topic, type(exc).__name__
            )
            return
        result_code = getattr(result, "rc", 0)
        try:
            failed = int(result_code) != 0
        except (TypeError, ValueError):
            failed = False
        if failed:
            self.log.warning("MQTT publish failed for %s (code %s)", topic, result_code)

    def publish_catalog(self, bindings: Iterable[AccessBinding]) -> None:
        snapshot = tuple(bindings)
        with self._lock:
            self._bindings = snapshot
            connected = self._connected
        if connected:
            self._publish_catalog_now(snapshot)

    def _publish_catalog_now(self, bindings: Iterable[AccessBinding]) -> None:
        for binding in bindings:
            base = f"{self.topic_prefix}/access/{binding.mqtt_key.value}"
            # Publish descriptive metadata before the discovery topic. On first
            # discovery SprutHub can then resolve the Name characteristic and
            # the read-only identification options immediately.
            self._publish(f"{base}/name", binding.point.title, retain=True)
            self._publish(f"{base}/kind", binding.point.kind.value, retain=True)
            self._publish(
                f"{base}/availability",
                "online" if binding.present else "offline",
                retain=True,
            )
            self._publish(
                f"{base}/camera_id", binding.point.camera_id or "", retain=True
            )
            self._publish(f"{base}/state", "OFF", retain=True)

    def publish_bridge_availability(self, online: bool) -> None:
        self._publish(
            f"{self.topic_prefix}/bridge/availability",
            "online" if online else "offline",
            retain=True,
        )

    def publish_open_succeeded(self, binding: AccessBinding) -> None:
        base = f"{self.topic_prefix}/access/{binding.mqtt_key.value}"
        # ON is intentionally not retained. The broker's retained state remains OFF,
        # so a restart or reconnect can never replay an open action.
        self._publish(f"{base}/state", "ON", retain=False)
        self._publish(f"{base}/result", "opened", retain=False)

        timer: threading.Timer

        def reset() -> None:
            self._publish(f"{base}/state", "OFF", retain=True)
            with self._lock:
                self._timers.discard(timer)

        timer = threading.Timer(self.pulse_seconds, reset)
        timer.daemon = True
        with self._lock:
            self._timers.add(timer)
        timer.start()

    def publish_open_failed(self, binding: AccessBinding, reason: str) -> None:
        base = f"{self.topic_prefix}/access/{binding.mqtt_key.value}"
        self._publish(f"{base}/state", "OFF", retain=True)
        self._publish(f"{base}/result", f"error:{reason}", retain=False)

    def publish_rejected(self, mqtt_key: str, reason: str) -> None:
        if not _MQTT_KEY_RE.fullmatch(mqtt_key):
            return
        self._publish(
            f"{self.topic_prefix}/access/{mqtt_key}/result",
            f"rejected:{reason}",
            retain=False,
        )
