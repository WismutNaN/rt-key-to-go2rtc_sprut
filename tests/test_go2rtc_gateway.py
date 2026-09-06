from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlsplit

from rtkey_gateway.domain import AudioMode, MediaProfile, SecretUrl, StreamName
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
        self.assertIn("#video=copy#audio=copy", query["src"][0])
        self.assertTrue(headers["Authorization"].startswith("Basic "))

    def test_audio_none_omits_audio_selector(self) -> None:
        source = build_go2rtc_source(
            SecretUrl("https://x.camera.rt.ru/live?token=secret"),
            MediaProfile(AudioMode.NONE),
        )
        self.assertEqual(source.count("#"), 1)
        self.assertNotIn("audio=", source)

    def test_redaction_removes_token(self) -> None:
        source = "ffmpeg:https://x.camera.rt.ru/live?token=topsecret&x=1#video=copy"
        redacted = redact_source(source)
        self.assertNotIn("topsecret", redacted)
        self.assertIn("token=%2A%2A%2A", redacted)


if __name__ == "__main__":
    unittest.main()
