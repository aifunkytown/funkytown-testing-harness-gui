# funkytown-testing-harness-gui

A local-only desktop front end (PySide6/Qt) for
[funkytown-testing-harness](https://github.com/aifunkytown/funkytown-testing-harness) -
build and run a model-comparison or LoRA-weight-sweep test config, or
generate prompt variations via
[comfy-prompt-tools](https://github.com/aifunkytown/comfy-prompt-tools)'s
`generate_prompt_variations.py`, without hand-editing JSON or the command
line.

## Setup

This project imports `funkytown_testing_harness` directly rather than
installing it as a package, and that project in turn imports
`comfy-prompt-tools` the same way - so both need to be on disk somewhere
this project can find them. Two ways to get all 3 repos in one shot instead
of three separate `git clone`s:

**Option A - one clone, with submodules** (`funkytown-testing-harness` and
`comfy-prompt-tools` come along nested inside this repo):

```bash
git clone --recurse-submodules https://github.com/aifunkytown/funkytown-testing-harness-gui.git
```

The submodules are pinned to whatever commit this repo's submodule
references currently point at - not automatically each repo's latest. Pull
the newest commit from each submodule's own default branch with:

```bash
git submodule update --remote --merge
```

**Option B - three clones, sibling layout** (the original way; useful if
you want each repo independently up to date without the submodule-pinning
behavior above). The parent folder can be named/located anything you like -
only the sibling relationship matters:

```
your-workspace/
├── comfy-prompt-tools/
├── funkytown-testing-harness/
└── funkytown-testing-harness-gui/
```

Either way, this project auto-detects which layout it's in (sibling
directories are checked first, so an existing Option B setup keeps working
even after submodules were added) - or override the location of either
dependency in Settings if you keep them somewhere else entirely.

```bash
pip install PySide6
python -m funkytown_testing_harness_gui.main
```

Or just double-click **`Launch funkytown-testing-harness-gui.exe`** at the
project root - see "Launcher exe" below.

## What it does

The window has two top-level tabs: **Testing** (build and run a
model-comparison or LoRA-weight-sweep config) and **Variations** (generate
prompt variations for one CSV row via Ollama).

- **First-run setup** - until a ComfyUI installation folder is configured,
  startup tries to infer one from a running ComfyUI server's own launch
  arguments and asks you to confirm it; if it can't infer one (server not
  running, or launched without `--base-directory`) or you say the guess is
  wrong, it opens Settings for you to set it manually. Runs every launch
  until something's actually configured.

### Testing tab

- **Workflow selector** (shared, top of the tab) - dropdown of workflow
  files found in your ComfyUI installation's `user/default/workflows` folder
  (configured in Settings), plus a positive-prompt override box. The **Use
  Default LoRAs** checkbox only applies on the Model tab (it's disabled on
  the LoRA tab, since a LoRA run needs those slots to stay present) -
  unchecked by default, meaning this run's queued workflow gets its Power
  Lora Loader node cleared; check it to leave the workflow's own LoRA setup
  as-is instead. Either way this only affects *this run's* queued workflow,
  not anything downstream: **Edit LoRA Rules...** next to it opens an
  editable table of `comfy-prompt-tools/rerun_prompts_comfyui.py`'s current
  keyword -> LoRA routing rules - add, edit, or remove rows and Save writes
  them to a gitignored `lora_rules.local.json` next to `lora_rules.json`
  (never committed), taking effect immediately. These rules independently
  turn a matching LoRA back on based on prompt text whenever a prompt is
  later rerun through that script, regardless of Use Default LoRAs above.
- **Model tab** - pick a model from a live-queried dropdown (from ComfyUI's
  `/object_info`) and "Add to list" builds up the model list - this is the
  *only* place model selection happens, for both a Models-only comparison
  run and any LoRA run. Double-click (or "Edit selected...") an entry to
  open its config window - check a field
  (sampler/steps/cfg/scheduler/seed/denoise) to override it, leave it
  unchecked to use the workflow's own value, and add multiple configs to run
  that model more than once. A tab is "active" for Run Test purely by having
  something in its list - there's no separate enable checkbox.
- **LoRA tab** - a "Combine LoRAs" checkbox (run every LoRA together across
  the cartesian product of their weights, instead of one at a time), then
  pick a LoRA from a live-queried dropdown (from ComfyUI's `LoraLoader`
  node) and "Add to list" to give it a list of weights to sweep. A LoRA
  must already exist as a slot in the workflow's Power Lora Loader
  (rgthree) node - a slot can be toggled here but not created. There's no
  model picker here any more - a LoRA run always uses whatever's on the
  Model tab.
- **Run Test** (below the tabs, shared) - what it does depends on which
  tab(s) have something in their list:
  - **Model only** - compares the Model tab's list against each other
    (requires at least 2), via `funkytown_testing_harness.run_test.run()`.
  - **LoRA populated** - sweeps the LoRA tab's LoRAs against whichever
    model(s) are on the Model tab (at least 1 required), via
    `funkytown_testing_harness.lora_test.run()`.

  Before anything is queued, a **Confirm test run** dialog shows the exact
  JSON that's about to be submitted, so you can check it over - Run to
  proceed, Cancel to back out and adjust something first. **Save Test...**
  sits next to Run Test and writes the same combined config to a file
  instead of running it (same as `File > Save Test...` below).
- **Settings window** - ComfyUI server URL, ComfyUI installation folder (for
  the workflow dropdown), and optional overrides for where
  `funkytown-testing-harness` and `comfy-prompt-tools` live if they aren't
  sibling directories.
- **File menu** - `File > Save Test...` writes the *combined* current state of
  both the Model tab and the LoRA tab together to one JSON file (defaults
  to `funkytown-testing-harness`'s `configs/` folder). If both tabs are
  empty it shows an error and writes nothing. `File > Import Test...` reads a
  JSON file back in and populates both tabs from it - each side only
  touches its own tab's data, and only if the file actually has that
  key, so importing an older single-schema file (just `"models"`, or just
  `"loras"`) combines into whatever's already on the other tab instead of
  wiping it out. An older lora_test.py config's singular `"model"` key (no
  `"models"` list) is folded into the Model tab's list the same way, since
  there's no separate LoRA-tab model field to hold it any more.

After confirming, the assembled config is written to this project's own
`gui_last_model_run.json` or `gui_last_lora_run.json` (gitignored, depending
on which `run()` function is being used) and run on a background thread so
the window doesn't freeze. Progress streams into the tab's own log panel at
the bottom, the same messages the CLI would print.

### Variations tab

Front end for `comfy_prompt_tools.generate_prompt_variations` - pick a CSV
file, which enables the **Min row**/**Max row** counters (disabled until
then) and sets them to the CSV's full row range (1 to its last data row) by
default; narrow them to target a single row or a smaller range. **Show
Prompts** (disabled until a CSV with at least one row is loaded) previews
the exact source text each row in that range will use - Cleaned Prompt if
the CSV has that column and it's non-empty for the row, otherwise Positive
Prompt, same preference `generate_prompt_variations.py` itself uses - so you
can sanity-check the row selection before spending an Ollama call on it.
Then either check one or more aspects from a list populated from
`prompt_aspect_vocab.json` (plus an optional free-text field for aspects not
in that file), or switch to "Random aspects" and pick how many to have
chosen randomly from the vocab file per row. Set a variation count and
(optionally) a different Ollama model, then **Generate Variations** - same
confirm-dialog-then-background-thread flow as the Testing tab's Run Test,
except the confirm dialog also lists each selected named aspect's full set
of possible values (for any that have a controlled vocabulary) so you can
see what the model can actually pick from before committing - that list is
preview-only and isn't written to the config that actually gets run. Writes
to this project's own `gui_last_variations_run.json` (gitignored) and
streams progress into the tab's own log panel. Output lands in a
`Variations` folder next to the input CSV, same as running the script from
the command line.

Once a Generate Variations run finishes successfully, **Queue Generated
Variations** (disabled until then) submits exactly the output file(s) that
run just wrote to ComfyUI via `comfy_prompt_tools.rerun_prompts_comfyui`,
using the Testing tab's Source workflow (resolved to a local file under
your ComfyUI installation's `user/default/workflows` folder) and Settings'
ComfyUI server - same confirm-dialog-then-background-thread flow, sharing
the tab's log panel, writing to a gitignored
`gui_last_queue_variations_run.json`. It always refers to the most recently
*successful* Generate Variations run - starting a new one before queuing
the previous one just replaces what Queue would submit next.

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
