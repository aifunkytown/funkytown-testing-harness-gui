"""Entry point: python -m funkytown_testing_harness_gui.main

Applies custom folder overrides from settings (if set) to sys.path *before*
anything imports funkytown_testing_harness, so they take precedence over the
default location guesses. Order matters: comfy-prompt-tools goes in first,
since funkytown_testing_harness's own modules look for it as soon as they're
imported.

There are two ways to get all 3 repos onto disk, both auto-detected below
(a Settings override always wins over either guess):
  - `git clone --recurse-submodules <this repo's URL>` - funkytown-testing-harness
    and comfy-prompt-tools come along as git submodules nested directly under
    this repo's root (see .gitmodules), pinned to whatever commit this repo's
    submodule references currently point at - not necessarily each repo's
    latest. Run `git submodule update --remote --merge` in this repo to pull
    the latest commit from each submodule's own default branch.
  - The older sibling-directory layout (each of the 3 repos cloned
    separately, next to each other) - checked first, so an existing setup
    built this way keeps working unchanged even after submodules were added.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = REPO_ROOT.parent


def _guess_dir(name):
    """Sibling-directory layout first (existing setups keep working
    unchanged), then this repo's own nested git submodule of the same name."""
    sibling = WORKSPACE_ROOT / name
    if sibling.is_dir():
        return sibling
    return REPO_ROOT / name


def main():
    from funkytown_testing_harness_gui.app_settings import load_settings

    settings = load_settings()

    comfy_prompt_tools_dir = settings.get("comfy_prompt_tools_dir") or str(_guess_dir("comfy-prompt-tools"))
    if comfy_prompt_tools_dir and comfy_prompt_tools_dir not in sys.path:
        sys.path.insert(0, comfy_prompt_tools_dir)

    harness_dir = settings.get("funkytown_testing_harness_dir") or str(_guess_dir("funkytown-testing-harness"))
    if harness_dir not in sys.path:
        sys.path.insert(0, harness_dir)

    try:
        import funkytown_testing_harness  # noqa: F401
    except ImportError:
        sys.exit(
            f"Error: could not import funkytown_testing_harness from {harness_dir}.\n"
            "Expected either a sibling directory next to funkytown-testing-harness-gui, "
            "or (if this repo was cloned with `git clone --recurse-submodules`) the "
            "nested funkytown-testing-harness submodule - or set a custom path in Settings."
        )

    from PySide6.QtWidgets import QApplication

    from funkytown_testing_harness_gui.main_window import MainWindow
    from funkytown_testing_harness_gui.theme import apply_theme

    app = QApplication(sys.argv)
    apply_theme(app, bool(settings.get("dark_mode", True)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
