"""Source checks that keep the project portable."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Sources(unittest.TestCase):
    def test_unix_line_endings(self):
        files = [ROOT / "main.py", ROOT / "version.py", ROOT / "README.md", ROOT / "MANUAL.md"]
        for folder in ("core", "ui", "tests"):
            files += sorted((ROOT / folder).glob("*.py"))
        for path in files:
            with self.subTest(path.name):
                self.assertNotIn(b"\r\n", path.read_bytes())

    def test_version(self):
        from version import VERSION

        self.assertRegex(VERSION, r"^\d+\.\d+$")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{VERSION}"', pyproject)

    def test_core_does_not_use_qt(self):
        for path in sorted((ROOT / "core").glob("*.py")):
            with self.subTest(path.name):
                self.assertNotIn("PySide6", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
