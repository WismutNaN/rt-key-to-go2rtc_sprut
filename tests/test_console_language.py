from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConsoleLanguageTests(unittest.TestCase):
    def test_maintained_console_entrypoints_are_ascii_only(self) -> None:
        paths = (
            ROOT / "install.sh",
            ROOT / "manage.sh",
            ROOT / "uninstall.sh",
            ROOT / "scripts/secrets.sh",
            ROOT / "src/rtkey_gateway/interfaces/cli.py",
        )
        for path in paths:
            with self.subTest(path=path.name):
                path.read_bytes().decode("ascii")


if __name__ == "__main__":
    unittest.main()
