"""Entry point: python -m funkytown_testing_harness_gui.main

Applies custom folder overrides from settings (if set) to sys.path *before*
anything imports funkytown_testing_harness, so they take precedence over the
default sibling-directory guesses. Order matters: comfy-prompt-tools goes in
first, since funkytown_testing_harness's own modules look for it as soon as
they're imported.
"""

import sys
from pathlib import Path


def main():
    from funkytown_testing_harness_gui.app_settings import load_settings

    settings = load_settings()

    comfy_prompt_tools_dir = settings.get("comfy_prompt_tools_dir")
    if comfy_prompt_tools_dir and comfy_prompt_tools_dir not in sys.path:
        sys.path.insert(0, comfy_prompt_tools_dir)

    harness_dir = settings.get("funkytown_testing_harness_dir") or str(
        Path(__file__).resolve().parent.parent.parent / "funkytown-testing-harness"
    )
    if harness_dir not in sys.path:
        sys.path.insert(0, harness_dir)

    try:
        import funkytown_testing_harness  # noqa: F401
    except ImportError:
        sys.exit(
            f"Error: could not import funkytown_testing_harness from {harness_dir}.\n"
            "Expected funkytown-testing-harness checked out as a sibling directory next "
            "to funkytown-testing-harness-gui (or set a custom path in Settings)."
        )

    from PySide6.QtWidgets import QApplication

    from funkytown_testing_harness_gui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
