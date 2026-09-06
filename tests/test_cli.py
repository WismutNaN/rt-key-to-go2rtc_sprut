from __future__ import annotations

import contextlib
import io
import tarfile
import time
import unittest
from types import SimpleNamespace

from rtkey_gateway.application.ports import MediaProbeResult
from rtkey_gateway.domain import (
    AccessBinding,
    AccessPoint,
    AccessPointId,
    AccessPointKind,
    AccessState,
    CameraBinding,
    CameraId,
    GatewayState,
    MediaPolicy,
    SecretUrl,
    StreamName,
    mqtt_device_key,
)
from rtkey_gateway.interfaces.cli import (
    command_access_show,
    command_export_access_templates,
    command_healthcheck,
    command_show,
)
from tests.helpers import MemoryRepository


class CliTests(unittest.TestCase):
    def test_show_waits_until_initial_stream_was_verified(self) -> None:
        state = GatewayState(
            bindings={
                "uid": CameraBinding(
                    CameraId("uid"), StreamName("camera"), "Camera"
                )
            }
        )
        container = SimpleNamespace(repository=MemoryRepository(state))
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            result = command_show(container)
        self.assertEqual(result, 2)
        self.assertIn("have not passed initial verification", error.getvalue())

    def test_show_prints_rtsp_and_snapshot_urls(self) -> None:
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
        settings = SimpleNamespace(
            rtsp_username="spruthub",
            rtsp_password="rtsp-password",
            rtsp_host="192.168.50.99",
            rtsp_port=8554,
            snapshot_port=8080,
            media_policy=MediaPolicy(),
        )
        container = SimpleNamespace(
            repository=MemoryRepository(state), settings=settings
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = command_show(container)
        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("SprutHub camera connection data", rendered)
        self.assertIn("Username: spruthub", rendered)
        self.assertIn("Camera: Подъезд [uid]", rendered)
        self.assertIn("Stream name: podezd", rendered)
        self.assertIn("Resolution: source", rendered)
        self.assertIn("Video mode: copy", rendered)
        self.assertIn("Audio: disabled", rendered)
        self.assertIn("rtsp://spruthub:rtsp-password@192.168.50.99:8554/podezd", rendered)
        self.assertIn(
            "http://spruthub:rtsp-password@192.168.50.99:8080/snapshot/podezd.jpg",
            rendered,
        )
        self.assertNotIn("podezd_1280x720", rendered)

    def test_automatic_healthcheck_does_not_probe_camera_streams(self) -> None:
        now = int(time.time())
        state = GatewayState(
            bindings={
                "uid": CameraBinding(
                    CameraId("uid"),
                    StreamName("camera"),
                    "Camera",
                    last_good_upstream=SecretUrl(
                        "https://live.camera.rt.ru/uid?token=secret"
                    ),
                    last_good_expires_at=now + 3_600,
                )
            },
            last_fetch_at=now,
        )

        class Probe:
            requested: set[str] | None = None

            def probe(self, streams: set[str]) -> MediaProbeResult:
                self.requested = streams
                return MediaProbeResult(True, frozenset())

        probe = Probe()
        container = SimpleNamespace(
            repository=MemoryRepository(state),
            media_gateway=SimpleNamespace(list_streams=lambda: {"camera"}),
            media_probe=probe,
            settings=SimpleNamespace(health_max_stale=21_600),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            result = command_healthcheck(container)
        self.assertEqual(result, 0)
        self.assertEqual(probe.requested, set())

    def test_access_show_prints_provider_title_and_mqtt_mapping(self) -> None:
        point = AccessPoint(
            AccessPointId("door-1"), AccessPointKind.INTERCOM, "Подъезд 1"
        )
        binding = AccessBinding(point, mqtt_device_key(point.kind, point.point_id))

        class Repository:
            def load(self) -> AccessState:
                return AccessState(
                    bindings={binding.identity: binding},
                    last_success_at=100,
                )

        container = SimpleNamespace(
            settings=SimpleNamespace(
                access_control="mqtt",
                mqtt_host="192.168.50.10",
                mqtt_port=44_444,
                mqtt_username="rtkey",
                mqtt_password="mqtt-password",
                mqtt_topic_prefix="rtkey",
            ),
            access_repository=Repository(),
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = command_access_show(container)
        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("SprutHub MQTT access control", rendered)
        self.assertIn("Template export: ./manage.sh access-templates", rendered)
        self.assertIn("Place: Подъезд 1", rendered)
        self.assertIn("Template file: rtkey_access_", rendered)
        self.assertIn(f"MQTT key: {binding.mqtt_key.value}", rendered)

        archive_data = io.BytesIO()
        self.assertEqual(command_export_access_templates(container, archive_data), 0)
        with tarfile.open(fileobj=io.BytesIO(archive_data.getvalue())) as archive:
            self.assertEqual(len(archive.getnames()), 1)


if __name__ == "__main__":
    unittest.main()
