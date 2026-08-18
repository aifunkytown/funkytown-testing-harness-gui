"""Source for Launch funkytown-testing-harness-gui.exe - a thin double-click
launcher, not a bundled app. It doesn't contain any of the actual GUI code;
it just finds a Python interpreter on PATH and runs
`python -m funkytown_testing_harness_gui.main` from the project root, with no
console window. Editing code in this project, funkytown-testing-harness, or
comfy-prompt-tools takes effect immediately - nothing here needs rebuilding
unless you change this launch logic itself (see README: "Rebuilding the
launcher").
"""

import shutil
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


def project_root():
    # When frozen by PyInstaller, __file__ isn't meaningful - the exe's own
    # location is what matters, and it's meant to live at the project root.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def find_interpreter():
    return shutil.which("pythonw") or shutil.which("python")


def show_error(message):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "funkytown-testing-harness-gui", 0x10)
    except Exception:
        print(message, file=sys.stderr)


def main():
    interpreter = find_interpreter()
    if not interpreter:
        show_error(
            "Could not find a Python interpreter on PATH.\n\n"
            "Install Python (with PATH enabled) and pip install PySide6, or run:\n"
            "python -m funkytown_testing_harness_gui.main"
        )
        sys.exit(1)

    creationflags = CREATE_NO_WINDOW if interpreter.lower().endswith("python.exe") else 0
    subprocess.Popen(
        [interpreter, "-m", "funkytown_testing_harness_gui.main"],
        cwd=str(project_root()),
        creationflags=creationflags,
    )


if __name__ == "__main__":
    main()
