from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from rtkey_gateway.domain import (
    AccessBinding,
    AccessPoint,
    AccessPointId,
    AccessPointKind,
    AccessState,
    mqtt_device_key,
)
from rtkey_gateway.infrastructure.json_access_state import JsonAccessStateRepository
from rtkey_gateway.infrastructure.mqtt_access import MqttAccessEvents


ROOT = Path(__file__).resolve().parents[1]


class FakeMqttClient:
    def __init__(self) -> None:
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.published: list[tuple[str, str, int, bool]] = []
        self.subscriptions = []
        self.credentials = None
        self.will = None

    def username_pw_set(self, username, password=None):  # noqa: ANN001
        self.credentials = (username, password)

    def will_set(self, topic, payload, qos=0, retain=False):  # noqa: ANN001
        self.will = (topic, payload, qos, retain)

    def reconnect_delay_set(self, min_delay, max_delay):  # noqa: ANN001
        self.delays = (min_delay, max_delay)

    def connect_async(self, host, port, keepalive):  # noqa: ANN001
        self.connection = (host, port, keepalive)
        return 0

    def loop_start(self):
        self.started = True

    def loop_stop(self):
        self.started = False

    def disconnect(self):
        return 0

    def subscribe(self, topic, qos=0):  # noqa: ANN001
        self.subscriptions.append((topic, qos))
        return 0, 1

    def publish(self, topic, payload=None, qos=0, retain=False):  # noqa: ANN001
        self.published.append((topic, payload, qos, retain))
        return SimpleNamespace(rc=0)

    def connect_successfully(self) -> None:
        self.on_connect(self, None, None, 0, None)

    def message(self, topic: str, payload: bytes, *, retain: bool = False) -> None:
        self.on_message(
            self,
            None,
            SimpleNamespace(topic=topic, payload=payload, retain=retain),
        )


def binding() -> AccessBinding:
    point = AccessPoint(
        AccessPointId("door-1"),
        AccessPointKind.INTERCOM,
        "Подъезд",
        camera_id="cam-1",
    )
    return AccessBinding(point, mqtt_device_key(point.kind, point.point_id))


class MqttAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeMqttClient()
        self.commands: list[str] = []
        self.events = MqttAccessEvents(
            "192.168.50.10",
            44_444,
            "rtkey",
            "mqtt-password",
            pulse_seconds=0.01,
            client_factory=lambda: self.client,
        )
        self.events.publish_catalog([binding()])
        self.events.start(lambda key: self.commands.append(key) or True)
        self.client.connect_successfully()

    def tearDown(self) -> None:
        self.events.stop()

    def test_catalog_is_retained_and_command_is_subscribed(self) -> None:
        key = binding().mqtt_key.value
        self.assertIn(("rtkey/access/+/set", 1), self.client.subscriptions)
        self.assertIn(
            (f"rtkey/access/{key}/state", "OFF", 1, True),
            self.client.published,
        )
        self.assertIn(
            (f"rtkey/access/{key}/name", "Подъезд", 1, True),
            self.client.published,
        )

    def test_only_non_retained_on_command_is_forwarded(self) -> None:
        key = binding().mqtt_key.value
        topic = f"rtkey/access/{key}/set"
        self.client.message(topic, b"ON", retain=True)
        self.client.message(topic, b"OFF")
        self.client.message(topic, b"ON")
        self.assertEqual(self.commands, [key])

    def test_success_pulse_never_retains_on(self) -> None:
        item = binding()
        self.events.publish_open_succeeded(item)
        time.sleep(0.03)
        topic = f"rtkey/access/{item.mqtt_key.value}/state"
        messages = [entry for entry in self.client.published if entry[0] == topic]
        self.assertIn((topic, "ON", 1, False), messages)
        self.assertEqual(messages[-1], (topic, "OFF", 1, True))
        self.assertFalse(any(payload == "ON" and retain for _, payload, _, retain in messages))


class AccessStateTests(unittest.TestCase):
    def test_state_round_trip_and_sanitized_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonAccessStateRepository(Path(directory) / "access.json")
            item = binding()
            state = AccessState(
                bindings={item.identity: item},
                last_fetch_at=100,
                last_success_at=100,
            )
            repository.save(state)
            loaded = repository.load()
            self.assertEqual(loaded.bindings[item.identity], item)
            self.assertEqual(repository.sanitized()["devices"][0]["title"], "Подъезд")

    def test_spruthub_template_uses_current_link_arrays(self) -> None:
        template = json.loads(
            (ROOT / "spruthub" / "rtkey_access.json").read_text(encoding="utf-8")
        )
        self.assertEqual(template["modelId"], "rtkey/access/([a-z0-9][a-z0-9_-]{0,63})/state")
        characteristic = template["services"][0]["characteristics"][0]
        self.assertIsInstance(characteristic["link"], list)
        self.assertEqual(characteristic["link"][0]["topicSet"], "rtkey/access/(1)/set")


if __name__ == "__main__":
    unittest.main()
