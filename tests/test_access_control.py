from __future__ import annotations

import unittest

from rtkey_gateway.application.access_control import AccessControlService
from rtkey_gateway.domain import (
    AccessCatalogSnapshot,
    AccessPoint,
    AccessPointId,
    AccessPointKind,
    AccessState,
)
from tests.helpers import FakeClock


class AccessRepository:
    def __init__(self) -> None:
        self.state = AccessState()

    def load(self) -> AccessState:
        return self.state

    def save(self, state: AccessState) -> None:
        self.state = state


class Provider:
    def __init__(self, point: AccessPoint) -> None:
        self.point = point
        self.opened: list[str] = []

    def fetch_access_points(self) -> AccessCatalogSnapshot:
        return AccessCatalogSnapshot(
            (self.point,), frozenset({self.point.kind})
        )

    def open_access_point(self, point_id: AccessPointId) -> None:
        self.opened.append(point_id.value)


class Events:
    def __init__(self) -> None:
        self.bindings = []
        self.availability: list[bool] = []
        self.succeeded = []
        self.failed = []
        self.rejected = []

    def start(self, command_handler):  # noqa: ANN001
        self.command_handler = command_handler

    def stop(self) -> None:
        pass

    def publish_catalog(self, bindings):  # noqa: ANN001
        self.bindings = list(bindings)

    def publish_bridge_availability(self, online: bool) -> None:
        self.availability.append(online)

    def publish_open_succeeded(self, binding):  # noqa: ANN001
        self.succeeded.append(binding)

    def publish_open_failed(self, binding, reason):  # noqa: ANN001
        self.failed.append((binding, reason))

    def publish_rejected(self, mqtt_key, reason):  # noqa: ANN001
        self.rejected.append((mqtt_key, reason))


class AccessControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.point = AccessPoint(
            AccessPointId("door-1"), AccessPointKind.INTERCOM, "Подъезд"
        )
        self.repository = AccessRepository()
        self.provider = Provider(self.point)
        self.events = Events()
        self.clock = FakeClock(1_000)
        self.service = AccessControlService(
            self.provider,
            self.repository,
            self.events,
            self.clock,
            open_cooldown=5,
        )

    def test_refresh_then_open_only_known_device(self) -> None:
        result = self.service.refresh_once()
        self.assertTrue(result.succeeded)
        mqtt_key = self.events.bindings[0].mqtt_key.value
        self.assertTrue(self.service.handle_command(mqtt_key))
        self.assertEqual(self.provider.opened, ["door-1"])
        self.assertEqual(len(self.events.succeeded), 1)

    def test_unknown_device_and_duplicate_are_rejected(self) -> None:
        self.service.refresh_once()
        mqtt_key = self.events.bindings[0].mqtt_key.value
        self.assertFalse(self.service.handle_command("intercom_unknown_0000000000"))
        self.assertTrue(self.service.handle_command(mqtt_key))
        self.assertFalse(self.service.handle_command(mqtt_key))
        self.assertEqual(self.provider.opened, ["door-1"])
        self.assertEqual(self.events.rejected[-1][1], "cooldown")

    def test_command_is_allowed_after_cooldown(self) -> None:
        self.service.refresh_once()
        mqtt_key = self.events.bindings[0].mqtt_key.value
        self.assertTrue(self.service.handle_command(mqtt_key))
        self.clock.now += 5
        self.assertTrue(self.service.handle_command(mqtt_key))
        self.assertEqual(self.provider.opened, ["door-1", "door-1"])


if __name__ == "__main__":
    unittest.main()
