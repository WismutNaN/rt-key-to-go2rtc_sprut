"""Narrow authenticated HTTP interface exposing only verified JPEG snapshots."""

from __future__ import annotations

import base64
import hmac
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from rtkey_gateway.application.snapshot import GetCameraSnapshot
from rtkey_gateway.errors import GatewayError, ValidationError


_SNAPSHOT_PATH = re.compile(r"^/snapshot/([a-z0-9][a-z0-9_-]{0,63})\.jpg$")


class SnapshotHttpService:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        query: GetCameraSnapshot,
        *,
        workers: int = 2,
        logger: logging.Logger | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.query = query
        self.log = logger or logging.getLogger(__name__)
        self.authorization = "Basic " + base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        self.capacity = threading.BoundedSemaphore(max(1, workers))
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "rtkey-snapshot"
            sys_version = ""

            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(30)

            def log_message(self, _format: str, *args: object) -> None:
                service.log.debug("Snapshot request from %s", self.client_address[0])

            def _empty(self, status: int, *, authenticate: bool = False) -> None:
                self.send_response(status)
                if authenticate:
                    self.send_header(
                        "WWW-Authenticate", 'Basic realm="RT Key snapshots"'
                    )
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                provided = self.headers.get("Authorization", "")
                if not hmac.compare_digest(provided, service.authorization):
                    self._empty(401, authenticate=True)
                    return

                match = _SNAPSHOT_PATH.fullmatch(urlsplit(self.path).path)
                if match is None:
                    self._empty(404)
                    return
                if not service.capacity.acquire(timeout=10):
                    self._empty(503)
                    return
                try:
                    jpeg = service.query.execute(match.group(1))
                except ValidationError:
                    self._empty(404)
                    return
                except GatewayError as exc:
                    service.log.warning("Snapshot generation failed: %s", exc)
                    self._empty(502)
                    return
                finally:
                    service.capacity.release()

                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Cache-Control", "private, max-age=5")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                try:
                    self.wfile.write(jpeg)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    service.log.debug("Snapshot client disconnected before response")

        return Handler

    def start(self) -> None:
        try:
            self.server = ThreadingHTTPServer(
                (self.host, self.port), self._handler()
            )
        except OSError as exc:
            raise ValidationError("Snapshot HTTP port could not be opened") from exc
        self.server.daemon_threads = True
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="snapshot-http",
            daemon=True,
        )
        self.thread.start()
        self.log.info("Snapshot HTTP interface is ready on port %d", self.port)

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
