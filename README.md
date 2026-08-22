# funkytown-testing-harness-gui

A local-only desktop front end (PySide6/Qt) for
[funkytown-testing-harness](https://github.com/aifunkytown/funkytown-testing-harness) -
build and run a model-comparison or LoRA-weight-sweep test config without
hand-editing JSON.

## Setup

This project imports `funkytown_testing_harness` directly rather than
installing it as a package, so it expects that project checked out as a
**sibling directory** next to this one (which in turn expects
`comfy-prompt-tools` as its own sibling). The parent folder can be
named/located anything you like - only the sibling relationship matters:

```
your-workspace/
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

- **First-run setup** - until a ComfyUI installation folder is configured,
  startup tries to infer one from a running ComfyUI server's own launch
  arguments and asks you to confirm it; if it can't infer one (server not
  running, or launched without `--base-directory`) or you say the guess is
  wrong, it opens Settings for you to set it manually. Runs every launch
  until something's actually configured.
- **Workflow selector** (shared, top of the window) - dropdown of workflow
  files found in your ComfyUI installation's `user/default/workflows` folder
  (configured in Settings), plus a positive-prompt override box. The Strip
  LoRAs checkbox only applies on the Models tab (it's disabled on the LoRA
  tab, since a LoRA run needs those slots to stay present).
- **Models tab** - an "Enable Models test" checkbox, then pick a model from
  a live-queried dropdown (from ComfyUI's `/object_info`) and "Add to list"
  builds up the models list. Double-click (or "Edit selected...") an entry
  to open its config window - check a field
  (sampler/steps/cfg/scheduler/seed/denoise) to override it, leave it
  unchecked to use the workflow's own value, and add multiple configs to run
  that model more than once.
- **LoRA tab** - an "Enable LoRA test" checkbox, a model dropdown (only used
  when this tab is enabled *without* Models also enabled - see "Run Test"
  below), a "Combine LoRAs" checkbox (run every LoRA together across the
  cartesian product of their weights, instead of one at a time), then pick a
  LoRA from a live-queried dropdown (from ComfyUI's `LoraLoader` node) and
  "Add to list" to give it a list of weights to sweep. A LoRA must already
  exist as a slot in the workflow's Power Lora Loader (rgthree) node - a
  slot can be toggled here but not created.
- **Run Test** (below the tabs, shared) - what it does depends on which
  tab(s) are enabled:
  - **Models only** - compares the Models tab's list against each other,
    via `funkytown_testing_harness.run_test.run()`.
  - **LoRA only** - sweeps the LoRA tab's LoRAs against its own model
    dropdown, via `funkytown_testing_harness.lora_test.run()`.
  - **Both enabled** - every model in the Models tab's list is run against
    every LoRA combination from the LoRA tab (the LoRA tab's own model
    dropdown is ignored in this case) - also via `lora_test.run()`, using
    its `"models"` list form.

  Before anything is queued, a **Confirm test run** dialog shows the exact
  JSON that's about to be submitted, so you can check it over - Run to
  proceed, Cancel to back out and adjust something first.
- **Settings window** - ComfyUI server URL, ComfyUI installation folder (for
  the workflow dropdown), and optional overrides for where
  `funkytown-testing-harness` and `comfy-prompt-tools` live if they aren't
  sibling directories.
- **Save Config.../Load Config...** - read and write the same JSON config
  formats `run_test.py`/`lora_test.py` use on the command line (defaults to
  that project's `configs/` folder), tab-aware - Save writes whichever
  format matches the currently-*visible* tab (independent of the enable
  checkboxes), and Load auto-detects the format (presence of a `"loras"`
  key) and switches to the matching tab. A config built in the GUI can be
  run headlessly later, or vice versa. (The combined Models+LoRA config
  produced by Run Test isn't currently save-able through this - only
  reachable via the confirmation dialog on an actual run.)

After confirming, the assembled config is written to this project's own
`gui_last_model_run.json` or `gui_last_lora_run.json` (gitignored, depending
on which `run()` function is being used) and run on a background thread so
the window doesn't freeze. Progress streams into the shared log panel at the
bottom, the same messages the CLI would print.

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
