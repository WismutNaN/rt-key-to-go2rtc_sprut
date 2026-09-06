from __future__ import annotations

import unittest

from rtkey_gateway.domain import (
    AccessCatalogSnapshot,
    AccessPoint,
    AccessPointId,
    AccessPointKind,
    AccessState,
    mqtt_device_key,
    reconcile_access_state,
)


class AccessDomainTests(unittest.TestCase):
    def test_mqtt_key_is_stable_safe_and_kind_specific(self) -> None:
        point_id = AccessPointId("door/123")
        first = mqtt_device_key(AccessPointKind.INTERCOM, point_id)
        second = mqtt_device_key(AccessPointKind.INTERCOM, point_id)
        barrier = mqtt_device_key(AccessPointKind.BARRIER, point_id)
        self.assertEqual(first, second)
        self.assertNotEqual(first, barrier)
        self.assertNotIn("/", first.value)
        self.assertLessEqual(len(first.value), 64)

    def test_partial_refresh_preserves_failed_category(self) -> None:
        intercom = AccessPoint(
            AccessPointId("1"), AccessPointKind.INTERCOM, "Entrance"
        )
        barrier = AccessPoint(
            AccessPointId("2"), AccessPointKind.BARRIER, "Parking"
        )
        initial = reconcile_access_state(
            AccessState(),
            AccessCatalogSnapshot(
                (intercom, barrier), frozenset(AccessPointKind)
            ),
            now=100,
        )
        updated = reconcile_access_state(
            initial,
            AccessCatalogSnapshot(
                (),
                frozenset({AccessPointKind.INTERCOM}),
                frozenset({AccessPointKind.BARRIER}),
            ),
            now=200,
        )
        self.assertFalse(updated.bindings[intercom.identity].present)
        self.assertTrue(updated.bindings[barrier.identity].present)
        self.assertIn("barrier", updated.last_error or "")

    def test_provider_title_controls_are_removed(self) -> None:
        point = AccessPoint(
            AccessPointId("1"), AccessPointKind.INTERCOM, "Door\nname\u0000"
        )
        self.assertEqual(point.title, "Doorname")


if __name__ == "__main__":
    unittest.main()
