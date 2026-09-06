from __future__ import annotations

import unittest

from rtkey_gateway.domain import AccessPointId, AccessPointKind
from rtkey_gateway.errors import AuthenticationError
from rtkey_gateway.infrastructure.rtkey.access_control import RtKeyAccessControl
from tests.helpers import QueueTransport, json_response


class TokenSource:
    def read(self) -> str:
        return "bearer-secret"


class RtKeyAccessAdapterTests(unittest.TestCase):
    def test_maps_intercoms_and_barriers(self) -> None:
        transport = QueueTransport(
            [
                json_response(
                    {
                        "data": {
                            "devices": [
                                {
                                    "id": 101,
                                    "camera_id": "cam-1",
                                    "name_by_company": "Подъезд 1",
                                }
                            ]
                        }
                    }
                ),
                json_response(
                    {
                        "data": {
                            "devices": [
                                {"id": "b-2", "name_by_company": "Шлагбаум"}
                            ]
                        }
                    }
                ),
            ]
        )
        snapshot = RtKeyAccessControl(transport, TokenSource()).fetch_access_points()
        self.assertEqual(snapshot.refreshed_kinds, frozenset(AccessPointKind))
        self.assertEqual(len(snapshot.points), 2)
        self.assertEqual(snapshot.points[0].point_id.value, "101")
        self.assertEqual(snapshot.points[0].camera_id, "cam-1")
        self.assertEqual(snapshot.points[1].kind, AccessPointKind.BARRIER)
        self.assertTrue(
            all(
                request[2]["Authorization"] == "Bearer bearer-secret"
                for request in transport.requests
            )
        )

    def test_one_failed_category_produces_partial_snapshot(self) -> None:
        transport = QueueTransport(
            [json_response({}, 500), json_response({"data": {"devices": []}})]
        )
        snapshot = RtKeyAccessControl(transport, TokenSource()).fetch_access_points()
        self.assertEqual(
            snapshot.refreshed_kinds, frozenset({AccessPointKind.BARRIER})
        )
        self.assertEqual(
            snapshot.failed_kinds, frozenset({AccessPointKind.INTERCOM})
        )

    def test_all_auth_failures_are_classified(self) -> None:
        transport = QueueTransport([json_response({}, 401), json_response({}, 403)])
        with self.assertRaises(AuthenticationError):
            RtKeyAccessControl(transport, TokenSource()).fetch_access_points()

    def test_open_uses_encoded_known_id_and_empty_post(self) -> None:
        transport = QueueTransport([json_response({}, 204)])
        RtKeyAccessControl(transport, TokenSource()).open_access_point(
            AccessPointId("door/id")
        )
        method, url, headers = transport.requests[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/door%2Fid/open"))
        self.assertEqual(headers["Content-Length"], "0")


if __name__ == "__main__":
    unittest.main()
