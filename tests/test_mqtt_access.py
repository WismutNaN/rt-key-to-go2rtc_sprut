from __future__ import annotations

import io
import json
import re
import tarfile
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
from rtkey_gateway.infrastructure.spruthub_templates import (
    build_spruthub_access_templates,
    build_spruthub_template_archive,
)


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
        published_topics = [topic for topic, *_ in self.client.published]
        self.assertLess(
            published_topics.index(f"rtkey/access/{key}/name"),
            published_topics.index(f"rtkey/access/{key}/state"),
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

    def test_spruthub_template_uses_static_place_names_and_exact_topics(self) -> None:
        item = binding()
        generated = build_spruthub_access_templates([item], "rtkey")[0]
        template = json.loads(generated.content)

        self.assertEqual(
            set(template),
            {"name", "manufacturer", "model", "modelIds", "services"},
        )
        self.assertNotIn("modelId", template)
        self.assertEqual(
            [template[field] for field in ("name", "manufacturer", "model")],
            ["Подъезд", "Подъезд", "Подъезд"],
        )

        key = item.mqtt_key.value
        state_topic = f"rtkey/access/{key}/state"
        self.assertIsNotNone(re.fullmatch(template["modelIds"][0], state_topic))
        self.assertIsNone(
            re.fullmatch(template["modelIds"][0], f"{state_topic}/unexpected")
        )

        service = template["services"][0]
        self.assertEqual(service["name"], "Подъезд")
        self.assertEqual(service["type"], "Switch")
        characteristics = service["characteristics"]
        self.assertEqual(
            [characteristic["type"] for characteristic in characteristics],
            ["On"],
        )
        link = characteristics[0]["link"][0]
        self.assertEqual(link["type"], "String")
        self.assertEqual(link["topicGet"], state_topic)
        self.assertEqual(link["topicSet"], f"rtkey/access/{key}/set")
        self.assertEqual(link["map"], {"false": "OFF", "true": "ON"})
        self.assertNotIn("options", template)
        self.assertRegex(
            generated.filename,
            rf"^rtkey_{re.escape(key)}_[0-9a-f]{{8}}\.json$",
        )

    def test_duplicate_place_names_get_distinct_stable_labels(self) -> None:
        first = binding()
        second_point = AccessPoint(
            AccessPointId("door-2"),
            AccessPointKind.INTERCOM,
            "Подъезд",
        )
        second = AccessBinding(
            second_point,
            mqtt_device_key(second_point.kind, second_point.point_id),
        )

        generated = build_spruthub_access_templates([first, second], "rtkey")
        self.assertEqual(len({item.display_name for item in generated}), 2)
        for item in generated:
            template = json.loads(item.content)
            self.assertRegex(item.display_name, r"^Подъезд \[[0-9a-f]{10}\]$")
            self.assertEqual(template["name"], item.display_name)
            self.assertEqual(template["manufacturer"], item.display_name)
            self.assertEqual(template["model"], item.display_name)
            self.assertEqual(template["services"][0]["name"], item.display_name)

    def test_template_archive_contains_only_generated_json_files(self) -> None:
        generated = build_spruthub_access_templates([binding()], "rtkey")
        archive_bytes = build_spruthub_template_archive(generated)
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
            self.assertEqual(archive.getnames(), [generated[0].filename])
            exported = archive.extractfile(generated[0].filename)
            self.assertIsNotNone(exported)
            self.assertEqual(exported.read(), generated[0].content)


if __name__ == "__main__":
    unittest.main()
