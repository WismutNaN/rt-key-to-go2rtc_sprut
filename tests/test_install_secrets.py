from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallSecretTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp())
        (self.workspace / "scripts").mkdir()
        shutil.copy2(ROOT / "install.sh", self.workspace / "install.sh")
        shutil.copy2(ROOT / "scripts" / "secrets.sh", self.workspace / "scripts" / "secrets.sh")

        fake_bin = self.workspace / "bin"
        fake_bin.mkdir()
        docker = fake_bin / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "if [[ \"${1:-}\" != compose ]]; then exit 2; fi\n"
            "shift\n"
            "case \"${1:-}\" in\n"
            "  version|config|up) exit 0 ;;\n"
            "  exec) printf 'camera ready\\n'; exit 0 ;;\n"
            "  *) exit 2 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment["PATH"] = f"{fake_bin}{os.pathsep}{self.environment['PATH']}"
        self.environment["SERVER_IP"] = "192.168.50.99"

    def tearDown(self) -> None:
        for path in self.workspace.rglob("*"):
            try:
                path.chmod(0o700 if path.is_dir() else 0o600)
            except OSError:
                pass
        shutil.rmtree(self.workspace)

    def run_install(self, token: str | None = None) -> None:
        environment = self.environment.copy()
        environment.pop("ACCESS_TOKEN", None)
        if token is not None:
            environment["ACCESS_TOKEN"] = token
        subprocess.run(
            ["bash", "install.sh"],
            cwd=self.workspace,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def assert_secret_layout(self, expected_token: str) -> None:
        secret_dir = self.workspace / "secrets"
        token_file = secret_dir / "rtkey_access_token"
        self.assertEqual(token_file.read_text(encoding="utf-8"), expected_token)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(secret_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(token_file.stat().st_mode), 0o444)

        env_file = self.workspace / ".env"
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        env_text = env_file.read_text(encoding="utf-8")
        self.assertNotIn("RTKEY_ACCESS_TOKEN", env_text)
        self.assertNotIn("VIDEO_MODE=", env_text)
        self.assertNotIn("VIDEO_FPS=", env_text)
        self.assertNotIn("VIDEO_RESOLUTIONS=", env_text)
        self.assertNotIn("VIDEO_OVERRIDES_JSON=", env_text)
        self.assertNotIn("AUDIO_MODE=", env_text)
        self.assertNotIn("AUDIO_OVERRIDES_JSON=", env_text)
        self.assertIn("SNAPSHOT_PORT=8080", env_text)
        self.assertIn("SNAPSHOT_CACHE_SECONDS=30", env_text)
        self.assertIn("ACCESS_CONTROL=off", env_text)
        self.assertIn("MQTT_PORT=44444", env_text)

    def test_install_writes_file_secret_outside_env(self) -> None:
        self.run_install("Bearer header.payload.signature")
        self.assert_secret_layout("header.payload.signature")

    def test_install_migrates_legacy_env_token(self) -> None:
        (self.workspace / ".env").write_text(
            "RTKEY_ACCESS_TOKEN=legacy.payload.signature\n"
            "RTSP_BIND_IP=192.168.50.99\n"
            "VIDEO_MODE=h264\n"
            "VIDEO_FPS=30\n"
            "VIDEO_RESOLUTIONS=source,1280x720,640x360\n"
            "VIDEO_OVERRIDES_JSON={\"uid\":\"h264\"}\n"
            "AUDIO_MODE=pcma\n",
            encoding="utf-8",
        )
        self.run_install()
        self.assert_secret_layout("legacy.payload.signature")


if __name__ == "__main__":
    unittest.main()
