from __future__ import annotations

import ast
import unittest
from pathlib import Path

from rtkey_gateway.application.health import evaluate_state
from rtkey_gateway.domain import CameraBinding, CameraId, GatewayState, StreamName


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "rtkey_gateway"


class HealthTests(unittest.TestCase):
    def test_degraded_but_working_stream_is_healthy(self) -> None:
        state = GatewayState(
            bindings={
                "uid": CameraBinding(
                    CameraId("uid"), StreamName("camera"), "Camera", last_error="retry"
                )
            },
            last_fetch_at=100,
            last_error="partial",
        )
        report = evaluate_state(
            state, now=200, runtime_streams={"camera"}, max_stale=1_000,
            rtsp_reachable=True, rtsp_streams={"camera"},
        )
        self.assertTrue(report.healthy)
        self.assertTrue(report.degraded)

    def test_expired_stream_is_unhealthy(self) -> None:
        state = GatewayState(
            bindings={
                "uid": CameraBinding(
                    CameraId("uid"), StreamName("camera"), "Camera",
                    last_good_expires_at=100,
                )
            },
            last_fetch_at=100,
        )
        report = evaluate_state(
            state, now=200, runtime_streams={"camera"}, max_stale=1_000,
            rtsp_reachable=True, rtsp_streams={"camera"},
        )
        self.assertFalse(report.healthy)

    def test_upstream_probe_failure_is_unhealthy(self) -> None:
        state = GatewayState(
            bindings={
                "uid": CameraBinding(
                    CameraId("uid"), StreamName("camera"), "Camera"
                )
            },
            last_fetch_at=100,
        )
        report = evaluate_state(
            state,
            now=200,
            runtime_streams={"camera"},
            max_stale=1_000,
            rtsp_reachable=True,
            rtsp_streams=set(),
        )
        self.assertFalse(report.healthy)
        self.assertTrue(any("upstream probe" in item for item in report.messages))


class ArchitectureTests(unittest.TestCase):
    def _imports(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        result: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                result.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                result.add(node.module)
        return result

    def test_dependency_direction(self) -> None:
        violations: list[str] = []
        for path in (SOURCE / "shared").glob("*.py"):
            for imported in self._imports(path):
                if any(
                    layer in imported
                    for layer in (
                        ".domain",
                        ".application",
                        ".infrastructure",
                        ".interfaces",
                    )
                ):
                    violations.append(f"shared/{path.name} -> {imported}")
        for path in (SOURCE / "domain").glob("*.py"):
            for imported in self._imports(path):
                if any(
                    layer in imported
                    for layer in (".application", ".infrastructure", ".interfaces")
                ):
                    violations.append(f"domain/{path.name} -> {imported}")
        for path in (SOURCE / "application").glob("*.py"):
            for imported in self._imports(path):
                if ".infrastructure" in imported or ".interfaces" in imported:
                    violations.append(f"application/{path.name} -> {imported}")
        self.assertEqual(violations, [])

    def test_compose_does_not_publish_go2rtc_api(self) -> None:
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertNotIn("1984:1984", compose)
        self.assertIn("RTSP_PORT", compose)
        self.assertIn("alexxit/go2rtc:1.9.14", compose)
        self.assertNotIn("alexxit/go2rtc:latest", compose)
        self.assertIn("file: ./secrets/rtkey_access_token", compose)
        self.assertNotIn("environment: RTKEY_ACCESS_TOKEN", compose)
        self.assertNotIn('uid: "10001"', compose)
        self.assertNotIn("mode: 0400", compose)
        self.assertNotIn("env_file:", compose)
        controller = compose.split("  controller:", 1)[1].split("\nnetworks:", 1)[0]
        self.assertNotIn("RTKEY_ACCESS_TOKEN:", controller)
        config = (ROOT / "go2rtc" / "go2rtc.yaml").read_text(encoding="utf-8")
        self.assertIn("local_auth: true", config)
        self.assertIn("/api/streams", config)
        self.assertIn("username:", config)
        self.assertIn("password:", config)
        self.assertIn('listen: ""', config)
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM python:3.12.14-alpine3.24", dockerfile)

    def test_runtime_secrets_are_ignored_but_static_config_is_not(self) -> None:
        patterns = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", patterns)
        self.assertIn("secrets/", patterns)
        self.assertIn("data/", patterns)
        self.assertNotIn("\ngo2rtc.yaml\n", f"\n{patterns}\n")

        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("secrets", dockerignore)


if __name__ == "__main__":
    unittest.main()
