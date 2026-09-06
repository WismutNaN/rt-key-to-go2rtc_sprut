from __future__ import annotations

import base64
import http.client
import unittest

from rtkey_gateway.application.snapshot import GetCameraSnapshot
from rtkey_gateway.domain import (
    CameraBinding,
    CameraId,
    GatewayState,
    MediaPolicy,
    SecretUrl,
    StreamName,
)
from rtkey_gateway.interfaces.snapshot_http import SnapshotHttpService
from tests.helpers import MemoryRepository


JPEG = b"\xff\xd8on-demand-frame\xff\xd9"


class SnapshotGateway:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def fetch_jpeg(self, name: StreamName) -> bytes:
        self.requests.append(name.value)
        return JPEG


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        state = GatewayState(
            bindings={
                "uid": CameraBinding(
                    CameraId("uid"),
                    StreamName("podezd"),
                    "Подъезд",
                    last_good_upstream=SecretUrl(
                        "https://live.camera.rt.ru/uid?token=secret"
                    ),
                )
            }
        )
        self.gateway = SnapshotGateway()
        self.service = SnapshotHttpService(
            "127.0.0.1",
            0,
            "spruthub",
            "rtsp-password",
            GetCameraSnapshot(MemoryRepository(state), self.gateway, MediaPolicy()),
        )
        self.service.start()
        assert self.service.server is not None
        self.port = int(self.service.server.server_address[1])

    def tearDown(self) -> None:
        self.service.stop()

    def request(self, path: str, *, authorized: bool) -> http.client.HTTPResponse:
        headers: dict[str, str] = {}
        if authorized:
            credentials = base64.b64encode(
                b"spruthub:rtsp-password"
            ).decode("ascii")
            headers["Authorization"] = f"Basic {credentials}"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", path, headers=headers)
        return connection.getresponse()

    def test_authenticated_snapshot_is_returned_on_demand(self) -> None:
        response = self.request("/snapshot/podezd.jpg", authorized=True)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "image/jpeg")
        self.assertEqual(response.read(), JPEG)
        self.assertEqual(self.gateway.requests, ["podezd"])

    def test_scaled_snapshot_variant_is_authorized_by_media_policy(self) -> None:
        response = self.request(
            "/snapshot/podezd_1280x720.jpg", authorized=True
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), JPEG)
        self.assertEqual(self.gateway.requests, ["podezd_1280x720"])

    def test_unknown_or_unauthenticated_path_does_not_touch_camera(self) -> None:
        unauthorized = self.request("/snapshot/podezd.jpg", authorized=False)
        self.assertEqual(unauthorized.status, 401)
        unauthorized.read()
        unknown = self.request("/snapshot/unknown.jpg", authorized=True)
        self.assertEqual(unknown.status, 404)
        unknown.read()
        self.assertEqual(self.gateway.requests, [])


if __name__ == "__main__":
    unittest.main()
