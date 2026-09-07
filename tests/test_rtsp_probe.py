from __future__ import annotations

import socket
import threading
import unittest

from rtkey_gateway.infrastructure.rtsp_probe import Go2RtcRtspProbe


class OneShotRtspServer:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.request = b""
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        connection, _address = self.listener.accept()
        with connection:
            self.request = connection.recv(4_096)
            connection.sendall(
                f"RTSP/1.0 {self.status} Test\r\nCSeq: 1\r\n\r\n".encode()
            )
        self.listener.close()

    def start(self) -> None:
        self.thread.start()

    def join(self) -> None:
        self.thread.join(timeout=2)


class RtspProbeTests(unittest.TestCase):
    def test_authenticated_describe_marks_stream_available(self) -> None:
        server = OneShotRtspServer()
        server.start()
        probe = Go2RtcRtspProbe(
            "127.0.0.1", server.port, "spruthub", "password", timeout=1
        )
        result = probe.probe({"podezd"})
        server.join()
        self.assertTrue(result.server_reachable)
        self.assertEqual(result.available_streams, frozenset({"podezd"}))
        self.assertIn(b"DESCRIBE rtsp://127.0.0.1", server.request)
        self.assertIn(b"/podezd?video RTSP/1.0", server.request)
        self.assertIn(b"Authorization: Basic", server.request)


if __name__ == "__main__":
    unittest.main()
