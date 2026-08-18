# funkytown-testing-harness-gui

A local-only desktop front end (PySide6/Qt) for
[funkytown-testing-harness](https://github.com/aifunkytown/funkytown-testing-harness) -
build and run a model-comparison test config without hand-editing JSON.

## Setup

This project imports `funkytown_testing_harness` directly rather than
installing it as a package, so it expects that project checked out as a
**sibling directory** next to this one (which in turn expects
`comfy-prompt-tools` as its own sibling):

```
Claude Projects/
├── comfy-prompt-tools/
├── funkytown-testing-harness/
└── funkytown-testing-harness-gui/
```

```bash
pip install PySide6
python -m funkytown_testing_harness_gui.main
```

Or just double-click **`Launch funkytown-testing-harness-gui.exe`** at the
project root - see "Launcher exe" below.

## What it does

- **Workflow selector** - dropdown of workflow files found in your ComfyUI
  installation's `user/default/workflows` folder (configured in Settings),
  plus a Strip LoRAs checkbox and a positive-prompt override box.
- **Model dropdowns** - pick a model from a live-queried dropdown (from
  ComfyUI's `/object_info`) and "Add to list" builds up the models-to-compare
  list. Double-click (or "Edit selected...") an entry to open its config
  window - check a field (sampler/steps/cfg/scheduler/seed/denoise) to
  override it, leave it unchecked to use the workflow's own value, and add
  multiple configs to run that model more than once.
- **Settings window** - ComfyUI server URL, ComfyUI installation folder (for
  the workflow dropdown), and optional overrides for where
  `funkytown-testing-harness` and `comfy-prompt-tools` live if they aren't
  sibling directories.
- **Save Config.../Load Config...** - read and write the same JSON config
  format `run_test.py` uses on the command line (defaults to that project's
  `configs/` folder), so a config built in the GUI can be run headlessly
  later, or vice versa.

Clicking **Run Test** writes the assembled config to this project's own
`gui_last_run.json` (gitignored) and runs it through
`funkytown_testing_harness.run_test.run()` - the exact function the CLI
uses - on a background thread so the window doesn't freeze. Progress streams
into the log panel at the bottom, the same messages the CLI would print.

There's no pass/fail in any of this (see the harness project's README for
why) - the GUI just makes it faster to build a config and watch it queue.

## Launcher exe

`Launch funkytown-testing-harness-gui.exe` at the project root is a **thin
launcher**, not a bundled app - it doesn't contain any of the actual GUI
code. Double-clicking it just finds a Python interpreter on PATH and runs
`python -m funkytown_testing_harness_gui.main` from the project root, with no
console window. Because none of the real code is baked into it, editing
anything in this project, `funkytown-testing-harness`, or
`comfy-prompt-tools` takes effect immediately, the next time you launch it -
no rebuilding, ever, unless you change the launch logic itself
(`launcher_src/launcher.py`).

It does still need Python + PySide6 installed and on PATH on whatever machine
runs it (same requirement as running the `.main` module directly) - it isn't
portable to a machine without Python.

### Rebuilding the launcher

Only needed if you edit `launcher_src/launcher.py`:

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name "Launch funkytown-testing-harness-gui" --distpath . --workpath build --specpath build launcher_src/launcher.py
```

`build/` (PyInstaller's intermediate output) is gitignored; the resulting
`.exe` at the project root is committed.
