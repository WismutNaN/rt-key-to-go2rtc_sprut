from __future__ import annotations

import contextlib
import io
import unittest
from types import SimpleNamespace

from rtkey_gateway.domain import CameraBinding, CameraId, GatewayState, StreamName
from rtkey_gateway.interfaces.cli import command_show
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
        self.assertIn("не прошли первичную проверку", error.getvalue())


if __name__ == "__main__":
    unittest.main()
