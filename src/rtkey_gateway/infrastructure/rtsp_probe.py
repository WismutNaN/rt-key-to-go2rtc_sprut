"""Short authenticated RTSP probes that validate go2rtc and lazy upstreams."""

from __future__ import annotations

import base64
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from rtkey_gateway.application.ports import MediaProbeResult


class Go2RtcRtspProbe:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        timeout: float = 5.0,
        workers: int = 4,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.workers = max(1, workers)
        self.authorization = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")

    def _request_status(self, stream_name: str | None) -> int | None:
        if stream_name is None:
            method = "OPTIONS"
            path = ""
        else:
            method = "DESCRIBE"
            path = f"{quote(stream_name, safe='-_')}?video"
        uri = f"rtsp://{self.host}:{self.port}/{path}"
        request = (
            f"{method} {uri} RTSP/1.0\r\n"
            "CSeq: 1\r\n"
            "User-Agent: rtkey-health\r\n"
            f"Authorization: Basic {self.authorization}\r\n"
            + ("Accept: application/sdp\r\n" if method == "DESCRIBE" else "")
            + "\r\n"
        ).encode("ascii")

        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            ) as connection:
                connection.settimeout(self.timeout)
                connection.sendall(request)
                response = bytearray()
                while b"\r\n" not in response and len(response) < 1_024:
                    chunk = connection.recv(1_024 - len(response))
                    if not chunk:
                        break
                    response.extend(chunk)
        except OSError:
            return None

        first_line = bytes(response).split(b"\r\n", 1)[0]
        parts = first_line.split()
        if len(parts) < 2 or parts[0] != b"RTSP/1.0":
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    def probe(self, stream_names: set[str]) -> MediaProbeResult:
        if not stream_names:
            return MediaProbeResult(
                server_reachable=self._request_status(None) is not None,
                available_streams=frozenset(),
            )

        ordered = sorted(stream_names)
        with ThreadPoolExecutor(
            max_workers=min(self.workers, len(ordered)),
            thread_name_prefix="rtsp-probe",
        ) as executor:
            statuses = list(executor.map(self._request_status, ordered))
        return MediaProbeResult(
            server_reachable=any(status is not None for status in statuses),
            available_streams=frozenset(
                name for name, status in zip(ordered, statuses) if status == 200
            ),
        )
