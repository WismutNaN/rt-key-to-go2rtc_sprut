"""go2rtc implementation of the MediaGatewayPort."""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import urlencode

from rtkey_gateway.domain import MediaProfile, SecretUrl, StreamName
from rtkey_gateway.errors import MediaGatewayError, SchemaError, TransportError
from rtkey_gateway.infrastructure.go2rtc_source import build_go2rtc_source
from rtkey_gateway.infrastructure.http import HttpTransport


class Go2RtcMediaGateway:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        transport: HttpTransport,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
            "User-Agent": "rtkey-go2rtc-gateway/1.0",
        }
        self.transport = transport
        self.timeout = timeout

    def _request(self, method: str, query: dict[str, str] | None = None):
        url = f"{self.base_url}/api/streams"
        if query:
            url = f"{url}?{urlencode(query)}"
        return self.transport.request(
            method, url, headers=self.headers, timeout=self.timeout
        )

    def list_streams(self) -> set[str]:
        response = self._request("GET")
        if response.status in {401, 403}:
            raise MediaGatewayError("go2rtc API authentication failed")
        if not 200 <= response.status < 300:
            raise MediaGatewayError(f"go2rtc API returned HTTP {response.status}")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SchemaError("go2rtc returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise SchemaError("go2rtc streams response is not an object")
        return {str(name) for name in payload}

    def wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.list_streams()
                return
            except (MediaGatewayError, SchemaError, TransportError) as exc:
                last_error = exc
                time.sleep(1.0)
        raise MediaGatewayError("go2rtc API did not become ready in time") from last_error

    def upsert_stream(
        self, name: StreamName, upstream_url: SecretUrl, profile: MediaProfile
    ) -> None:
        source = build_go2rtc_source(upstream_url, profile)
        response = self._request(
            "PATCH", {"name": name.value, "src": source}
        )
        if response.status in {401, 403}:
            raise MediaGatewayError("go2rtc API authentication failed")
        if not 200 <= response.status < 300:
            raise MediaGatewayError(
                f"go2rtc rejected stream {name.value!r} with HTTP {response.status}"
            )
        if name.value not in self.list_streams():
            raise MediaGatewayError(
                f"go2rtc did not expose updated stream {name.value!r}"
            )
