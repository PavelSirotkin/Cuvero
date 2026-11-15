"""Build Cuvero as one self-contained executable file with Nuitka.

    python build.py              dist/Cuvero.exe (dist/Cuvero on Linux)
    python build.py --clean      remove the old build first

Needs Nuitka (pip install nuitka) and a C compiler. On Windows Nuitka downloads one
itself (zig) on the first run; on Linux it uses gcc. The result runs without Python.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
NAME = "Cuvero"


def version() -> str:
    """The program version from version.py, padded to four numbers for Windows."""
    from version import VERSION

    numbers = re.findall(r"\d+", VERSION)[:4]
    return ".".join(numbers + ["0"] * (4 - len(numbers)))


def qt_translation() -> str:
    """Russian texts of Qt's standard dialogs, copied next to the program."""
    from PySide6.QtCore import QLibraryInfo

    folder = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    return f"--include-data-files={folder / 'qtbase_ru.qm'}=translations/qtbase_ru.qm"


def command() -> list[str]:
    args = [
        sys.executable,
        "-m",
        "nuitka",
        "--onefile",
        "--enable-plugin=pyside6",
        "--assume-yes-for-downloads",
        f"--output-dir={DIST}",
        f"--output-filename={NAME}",
        "--include-data-files=icon.ico=icon.ico",
        qt_translation(),
        # Only the program: tests, the format probes and the checkers stay out.
        "--nofollow-import-to=tests",
        "--nofollow-import-to=pytest,unittest,mypy,ruff",
        f"--product-name={NAME}",
        f"--product-version={version()}",
        f"--file-version={version()}",
        "--file-description=Cuvero — редактор печатных плат .lay6",
        "--company-name=The Cuvero authors",
        "--copyright=MIT License, The Cuvero authors",
    ]
    if sys.platform == "win32":
        args += ["--windows-console-mode=disable", "--windows-icon-from-ico=icon.ico"]
    elif sys.platform == "darwin":
        args += ["--macos-create-app-bundle", f"--macos-app-name={NAME}"]
    else:
        args += ["--linux-icon=icon.ico"]
    return [*args, "main.py"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Cuvero as one executable with Nuitka.")
    parser.add_argument("--clean", action="store_true", help="remove the old build first")
    options = parser.parse_args()
    if options.clean and DIST.exists():
        shutil.rmtree(DIST)
    args = command()
    print(" ".join(args), flush=True)
    result = subprocess.run(args, cwd=ROOT, check=False)
    if result.returncode:
        return result.returncode
    suffix = ".exe" if sys.platform == "win32" else ""
    print(f"\nГотово: {DIST / (NAME + suffix)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
