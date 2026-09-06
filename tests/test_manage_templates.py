from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManageTemplateExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp())
        (self.workspace / "scripts").mkdir()
        shutil.copy2(ROOT / "manage.sh", self.workspace / "manage.sh")
        shutil.copy2(
            ROOT / "scripts" / "secrets.sh",
            self.workspace / "scripts" / "secrets.sh",
        )
        (self.workspace / ".env").write_text("ACCESS_CONTROL=mqtt\n", encoding="ascii")

        archive_path = self.workspace / "templates.tar"
        content = b'{"name":"Entrance"}\n'
        archive_data = io.BytesIO()
        with tarfile.open(fileobj=archive_data, mode="w") as archive:
            info = tarfile.TarInfo("rtkey_access_12345678.json")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        archive_path.write_bytes(archive_data.getvalue())

        fake_bin = self.workspace / "bin"
        fake_bin.mkdir()
        docker = fake_bin / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            "[[ \"$*\" == *export-access-templates* ]] || exit 2\n"
            "exec cat \"$FAKE_TEMPLATE_ARCHIVE\"\n",
            encoding="ascii",
        )
        docker.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment["PATH"] = (
            f"{fake_bin}{os.pathsep}{self.environment['PATH']}"
        )
        self.environment["FAKE_TEMPLATE_ARCHIVE"] = archive_path.as_posix()

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace)

    def test_access_templates_extracts_named_json_without_docker(self) -> None:
        result = subprocess.run(
            ["bash", "manage.sh", "access-templates"],
            cwd=self.workspace,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        files = list((self.workspace / "generated").glob("*/*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_text(encoding="utf-8"), '{"name":"Entrance"}\n')
        self.assertIn("SprutHub access template created:", result.stdout)


if __name__ == "__main__":
    unittest.main()
