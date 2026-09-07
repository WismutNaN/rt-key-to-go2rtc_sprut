from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlsplit

from rtkey_gateway.domain import (
    AudioMode,
    MediaPolicy,
    MediaProfile,
    SecretUrl,
    StreamName,
)
from rtkey_gateway.infrastructure.go2rtc_gateway import Go2RtcMediaGateway
from rtkey_gateway.infrastructure.go2rtc_source import build_go2rtc_source, redact_source
from rtkey_gateway.infrastructure.http import HttpResponse


class Go2RtcTransport:
    def __init__(self) -> None:
        self.streams: set[str] = set()
        self.requests: list[tuple[str, str, dict[str, str]]] = []

    def request(self, method, url, *, headers=None, timeout=20.0):  # noqa: ANN001
        headers = dict(headers or {})
        self.requests.append((method, url, headers))
        if method == "PATCH":
            query = parse_qs(urlsplit(url).query)
            self.streams.add(query["name"][0])
            return HttpResponse(200, b"", {})
        if urlsplit(url).path == "/api/frame.jpeg":
            return HttpResponse(200, b"\xff\xd8jpeg\xff\xd9", {"Content-Type": "image/jpeg"})
        return HttpResponse(200, json.dumps({name: {} for name in self.streams}).encode(), {})


class Go2RtcGatewayTests(unittest.TestCase):
    def test_patch_creates_runtime_stream_and_uses_basic_auth(self) -> None:
        transport = Go2RtcTransport()
        gateway = Go2RtcMediaGateway(
            "http://go2rtc:1984", "controller", "secret", transport
        )
        gateway.upsert_stream(
            StreamName("podezd"),
            SecretUrl("https://live.camera.rt.ru/stream/id/live.mp4?token=a+b"),
            MediaProfile(AudioMode.COPY),
        )
        method, url, headers = transport.requests[0]
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(method, "PATCH")
        self.assertEqual(query["name"], ["podezd"])
        self.assertIn(
            "#video=rtkey_h264_copy#raw=rtkey_low_latency#audio=copy",
            query["src"][0],
        )
        self.assertTrue(headers["Authorization"].startswith("Basic "))

    def test_audio_none_omits_audio_selector(self) -> None:
        source = build_go2rtc_source(
            SecretUrl("https://x.camera.rt.ru/live?token=secret"),
            MediaProfile(AudioMode.NONE),
        )
        self.assertIn(
            "#input=rtkey_http#video=rtkey_h264_copy#raw=rtkey_low_latency",
            source,
        )
        self.assertNotIn("audio=", source)

    def test_default_policy_builds_video_only_source(self) -> None:
        profile = MediaPolicy().profile_for("uid")
        source = build_go2rtc_source(
            SecretUrl("https://x.camera.rt.ru/live?token=secret"),
            profile,
        )
        self.assertEqual(profile.audio_mode, AudioMode.NONE)
        self.assertIn("#raw=rtkey_low_latency", source)
        self.assertNotIn("audio=", source)

    def test_snapshot_uses_internal_authenticated_api(self) -> None:
        transport = Go2RtcTransport()
        gateway = Go2RtcMediaGateway(
            "http://go2rtc:1984", "controller", "secret", transport
        )
        self.assertEqual(
            gateway.fetch_jpeg(StreamName("podezd")),
            b"\xff\xd8jpeg\xff\xd9",
        )
        method, url, headers = transport.requests[0]
        self.assertEqual(method, "GET")
        self.assertEqual(urlsplit(url).path, "/api/frame.jpeg")
        self.assertEqual(parse_qs(urlsplit(url).query)["src"], ["podezd"])
        self.assertEqual(parse_qs(urlsplit(url).query)["cache"], ["30s"])
        self.assertTrue(headers["Authorization"].startswith("Basic "))

    def test_redaction_removes_token(self) -> None:
        source = "ffmpeg:https://x.camera.rt.ru/live?token=topsecret&x=1#video=copy"
        redacted = redact_source(source)
        self.assertNotIn("topsecret", redacted)
        self.assertIn("token=%2A%2A%2A", redacted)


if __name__ == "__main__":
    unittest.main()
