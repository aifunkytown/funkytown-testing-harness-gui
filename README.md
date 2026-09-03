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
pip install PySide6 Pillow
python -m funkytown_testing_harness_gui.main
```

(Pillow is only needed for the Results tab's "Create Grid" button, which
calls straight into `funkytown-testing-harness`'s own `comparison_grid.py`.)

Or just double-click **`Launch funkytown-testing-harness-gui.exe`** at the
project root - see "Launcher exe" below.

## What it does

The window has four top-level tabs: **Testing** (build and run a
model-comparison or LoRA-weight-sweep config), **Variations** (generate
prompt variations for one CSV row via Ollama), **Results** (browse
previous runs' output images), and **Generations** (extract, clean, and
content-rate a whole directory of images via Ollama).

- **First-run setup** - until a ComfyUI installation folder is configured,
  startup tries to infer one from a running ComfyUI server's own launch
  arguments and asks you to confirm it; if it can't infer one (server not
  running, or launched without `--base-directory`) or you say the guess is
  wrong, it opens Settings for you to set it manually. Runs every launch
  until something's actually configured.

### Testing tab

- **Workflow selector** (shared, top of the tab) - dropdown of workflow
  files found in your ComfyUI installation's `user/default/workflows` folder
  (configured in Settings), plus a **Prompt** section - **Prompts...** opens
  a popup listing the current prompt list, each as its own row with a ✕
  button to remove it, plus a text box at the bottom to type and add a new
  one (existing rows aren't directly text-editable - remove and re-add to
  change one's wording). A summary next to the button shows what's
  currently set. No prompts means use the workflow's own; one means
  override it; two or more sweeps every model/LoRA combo configured on the
  Model/LoRA tabs against each one - e.g. 2 models x 4 LoRA combinations x
  10 prompts queues 80 runs (requires `funkytown-testing-harness`'s
  `"positive_prompts"` config support). **Load from CSV** plus **Min
  row**/**Max row** counters populate the list with a CSV's resolved prompt
  text (Cleaned Prompt if present, otherwise Positive Prompt) - one entry
  per row, defaulting to the CSV's full row range; changing the CSV file or
  the row range always overwrites the list with a fresh pull. Once loaded,
  prompts can be freely removed via the popup (never writes back to the
  source CSV) - a red **edited** label appears next to Max row whenever the
  list no longer matches a fresh pull of the current CSV/row range. **Clear**
  next to Browse resets the CSV path, Min/Max row, and the prompt list
  itself back to empty - a full reset, not just detaching the list from
  its source. The **Use Default LoRAs**
  checkbox only applies on the Model tab (it's
  disabled on the LoRA tab, since a LoRA run needs those slots to stay present) -
  unchecked by default, meaning this run's queued workflow gets its Power
  Lora Loader node cleared; check it to leave the workflow's own LoRA setup
  as-is instead. Either way this only affects *this run's* queued workflow,
  not anything downstream: **Edit LoRA Rules...** next to it opens an
  editable table of `comfy-prompt-tools/rerun_prompts_comfyui.py`'s current
  keyword -> LoRA routing rules - click a cell to edit it inline (Enter or
  clicking away saves it), Add/Remove rows, and Save writes them to a
  gitignored `lora_rules.local.json` next to `lora_rules.json` (never
  committed), taking effect immediately. These rules independently turn a
  matching LoRA back on based on prompt text whenever a prompt is later
  rerun through that script, regardless of Use Default LoRAs above.
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
  node) and "Add to list" to give it a list of weights to sweep - the weight
  entry box starts blank (no default value) and its arrows step by whole
  numbers, so it's always clear you have to actually enter one. A LoRA
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
- **Settings window** (opened via the **Settings...** button, top right) -
  ComfyUI server URL, ComfyUI installation folder (for the workflow
  dropdown), and optional overrides for where `funkytown-testing-harness`
  and `comfy-prompt-tools` live if they aren't sibling directories.
- **File menu** - `File > Save Test...` writes the *combined* current state of
  both the Model tab and the LoRA tab together to one JSON file. Defaults
  to whichever file you last saved to or imported from this session; with
  neither, it suggests a name built from the currently selected models plus
  today's date (e.g. `modelA_modelB_2026-08-29.json`) in
  `funkytown-testing-harness`'s `configs/` folder. If both tabs are
  empty it shows an error and writes nothing. `File > Import Test...` reads a
  JSON file back in and populates both tabs from it - each side only
  touches its own tab's data, and only if the file actually has that
  key, so importing an older single-schema file (just `"models"`, or just
  `"loras"`) combines into whatever's already on the other tab instead of
  wiping it out. An older lora_test.py config's singular `"model"` key (no
  `"models"` list) is folded into the Model tab's list the same way, since
  there's no separate LoRA-tab model field to hold it any more. Also saves
  the prompt list's exact current content (`"positive_prompt"` for 0-1
  prompts, `"positive_prompts"` for 2+) - not a live CSV reference, so an
  edited/trimmed list round-trips exactly as saved. If a CSV was used
  to load it, `"positive_prompts_csv"`/`"positive_prompts_min_row"`/
  `"positive_prompts_max_row"` are also saved purely as a convenience for
  reloading that picker later; importing recomputes the **edited** label
  against a fresh pull of that CSV/range rather than trusting a stale flag.
- **Settings menu** - **Hide Explicit**, checked by default and persisted
  across launches - hides any aspect `prompt_aspect_vocab.json` marks
  explicit (its `_explicit_aspects` list) from the Variations tab's aspect
  checklist. Uncheck it to reveal them again. **Dark Mode**, also checked by
  default and persisted - switches the whole app to a dark Fusion palette;
  toggling it applies immediately, no restart needed.

After confirming, the assembled config is written to this project's own
`gui_last_model_run.json` or `gui_last_lora_run.json` (gitignored, depending
on which `run()` function is being used) and run on a background thread so
the window doesn't freeze. Progress streams into the tab's own collapsible
**Log** section at the bottom (collapsed by default - click the arrow to
expand; the window grows to fit it, so it's never clipped or hidden), the
same messages the CLI would print.

### Variations tab

Front end for `comfy_prompt_tools.generate_prompt_variations` - pick a CSV
file, which enables the **Min row**/**Max row** counters (disabled until
then) and sets them to the CSV's full row range (1 to its last data row) by
default; narrow them to target a single row or a smaller range. Changing
the CSV file or the row range populates the **Prompts** list below with
each selected row's resolved source text (Cleaned Prompt if the CSV has
that column and it's non-empty for the row, otherwise Positive Prompt,
same preference `generate_prompt_variations.py` itself uses) - click a line
to edit its text (overriding what gets varied for that row, while every
other column - File Name, Negative Prompt, etc. - still comes from the CSV
row as normal), or select a line and **Remove selected** to skip that row
entirely; neither ever touches the source CSV file. Unlike the Testing
tab's Prompts popup, no new unattached lines can be added here - each line is
always tied to a specific CSV row, since a Variations run needs that row's
other metadata to write its output. A red **edited** label appears next to
Max row whenever the list no longer matches a fresh pull of the current
CSV/row range; changing the CSV file or the row range always repopulates
the list fresh, discarding any edits/removals made under the previous
selection. Then either check one or more aspects from a list populated from
`prompt_aspect_vocab.json` (plus an optional free-text field for aspects not
in that file) - aspects the vocab file marks explicit are hidden here by
default, see Settings > Hide Explicit above - or switch to "Random aspects"
and pick how many to have
chosen randomly from the vocab file per row. Set a variation count and
(optionally) a different **Ollama model** - a dropdown populated from
whatever's currently pulled locally (`ollama list`, via Ollama's own
`/api/tags`), defaulting to `generate_prompt_variations.DEFAULT_MODEL`; it's
still editable by hand if Ollama isn't reachable or the model you want isn't
listed. Then **Generate Variations** - same
confirm-dialog-then-background-thread flow as the Testing tab's Run Test,
except the confirm dialog also lists each selected named aspect's full set
of possible values (for any that have a controlled vocabulary) so you can
see what the model can actually pick from before committing - that list is
preview-only and isn't written to the config that actually gets run. Writes
to this project's own `gui_last_variations_run.json` (gitignored) and
streams progress into the tab's own collapsible Log section. Output lands
in a `Variations` folder next to the input CSV, same as running the script
from the command line.

Once a Generate Variations run finishes successfully, **Queue Generated
Variations** (disabled until then) submits exactly the output file(s) that
run just wrote to ComfyUI via `comfy_prompt_tools.rerun_prompts_comfyui`,
using the Testing tab's Source workflow (resolved to a local file under
your ComfyUI installation's `user/default/workflows` folder) and Settings'
ComfyUI server - same confirm-dialog-then-background-thread flow, sharing
the tab's Log section, writing to a gitignored
`gui_last_queue_variations_run.json`. It always refers to the most recently
*successful* Generate Variations run - starting a new one before queuing
the previous one just replaces what Queue would submit next.

There's no pass/fail in any of this (see the harness project's README for
why) - the GUI just makes it faster to build a config and watch it queue.

### Results tab

A split view: the left side lists every logged run from
`funkytown-testing-harness`'s `runs/` folder, ordered by when each run
actually started (parsed from its log filename's own timestamp, not the
file's last-modified time - a long-running test's log keeps getting
rewritten as it goes, so mtime alone can put it out of order relative to a
shorter run that started later but finished first) - both Model/LoRA
test runs (`run_test.py`/`lora_test.py`) and Variations runs that were
queued to ComfyUI (a "Queue Generated Variations" run writes its own log
there too, alongside the Testing tab's, instead of the single shared
`rerun_log.csv` `rerun_prompts_comfyui.py` normally overwrites on every
invocation - so each queue run gets its own permanent entry here). Each
entry shows how many prompts it queued, with its own checkbox (unchecked by
default) plus a **Select All** above the list for bulk actions - currently
just **Delete selected** below, which now deletes every checked run's log
and output images in one confirmation instead of one at a time. Checking a
run is independent of *viewing* it: nothing is shown by default - the right
side stays blank until you click a run (regardless of its checkbox), which
fills it with
a tightly-packed, checkable grid of thumbnails for its output images -
never the OS file browser. Thumbnails load in the background ("Loading
images..." shows while it's in progress) so selecting a run with a lot of
output doesn't freeze the window - each one appears as its own file finishes
loading rather than the whole grid popping in at once. Every thumbnail
starts checked (so Create Grid below works immediately without having to
select anything first) - click one to uncheck/recheck it individually
(shown as a green checkmark badge over its bottom-left corner) -
Shift+click toggles-on every thumbnail between it and the last one you
plain-clicked, Windows-Explorer-style, without touching anything outside
that range - or **Select All** to check/uncheck every thumbnail at once;
double-click one to view it full size, with **&lt;**/**&gt;** buttons to step
through the rest of that run's images without closing the viewer - stepping
past the last image wraps back to the first, and past the first wraps to
the last - and a **Save & Close** button that saves a copy elsewhere
(defaulting to the same folder the run's own images live in) and closes the
viewer once the save actually completes; cancelling the save dialog leaves
the viewer open. The viewer also shows that image's prompt text underneath, when
its run's log recorded one - only a multi-prompt Model/LoRA sweep does (a
single/default-prompt run, or a Variations Queue run, has nothing recorded
to show, so it says so instead). **Refresh** re-scans the folder and stays on whichever run
was already selected, just bringing its image grid up to date (also done
automatically after Run Test or Queue Generated Variations finishes);
**Create Grid** builds a labeled
side-by-side comparison image from whichever images are currently checked
(at least 2 required) - one column per model/LoRA combo, up to 10 per
image; checking more than that produces additional numbered files (each
shown in its own viewer, one after another) instead of a taller image -
saved under `funkytown-testing-harness`'s `runs/grids/` folder, each opened
the same way a thumbnail does except its viewer also has a **Save** button
for exporting a copy elsewhere, defaulting to the same folder the run's own
output images live in. None of this polls ComfyUI, it
just globs whatever's currently on disk under your configured ComfyUI
installation's `output` folder for that run's logged filename prefixes, so
a still-in-progress run is fine to select or grid - it just shows/uses
fewer images than it'll end up with. Requires the ComfyUI installation
folder to be set in Settings (same setting the Workflow selector uses).

Each `run_test.py`/`lora_test.py` run writes its images under their own
`tests/<name>/<run_id>/...` directory (`run_id` a shortened timestamp of
when the run started, fresh per run) rather than everyone sharing
`tests/<name>/...`, so two runs with the same name never comingle their
images - this is what makes a precise per-run image snapshot possible at
all. Each image's filename also starts with a zero-padded queue number, so
sorting by name (including in the thumbnail grid here) always matches the
order things were actually queued in, regardless of how model/LoRA names
alphabetize.

### Generations tab

Scans a directory of images (`comfy_prompt_tools.extract_and_clean`) and
runs the full extract -> clean -> rate pipeline on it: each image's
embedded generation metadata is read, its prompt is rewritten for a modern
text-to-image model, and content-rated - all via a local Ollama model, in
one call per image (see `comfy-prompt-tools`'s `clean_prompts.py`). An
image with no metadata at all is described directly from the image itself
instead of being skipped. **Directory** plus **Browse...** choose what to
scan (recursively, same as `extract_image_prompts.py`) - the right side
fills with a lazy-loaded preview grid of every image found there, same
loading behavior as the Results tab's gallery; double-click one to view it
full size, with the same **&lt;**/**&gt;** step-through navigation. **Ollama
model** defaults to `clean_prompts.py`'s own default (independent of the
Variations tab's model choice); **Overwrite** reprocesses rows that already
have a Cleaned Prompt instead of skipping them. **Queue for Extraction/
Cleaning/Rating** runs the pipeline in the background, streaming progress
into the collapsible **Log** below - the preview gallery refreshes once it
finishes (the images themselves don't change, just their CSV metadata, but
this confirms the run completed against the same directory).

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
