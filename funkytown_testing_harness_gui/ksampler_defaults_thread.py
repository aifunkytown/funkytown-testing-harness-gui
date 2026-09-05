"""Background fetch of the currently-referenced workflow's own KSampler
values (sampler/steps/cfg/scheduler/seed/denoise), so the "Add Model"
dialog can default to whatever the workflow actually uses right now
instead of arbitrary numbers. Runs on a thread since it goes through the
same live fetch+convert as run_test.py (can take a few seconds, launches a
headless browser) and shouldn't freeze the window at startup or when the
workflow selection changes.
"""

from PySide6.QtCore import QThread, Signal

from funkytown_testing_harness.live_workflow import load_live_template
from funkytown_testing_harness.run_test import find_ksampler_node_id

KSAMPLER_DEFAULT_KEYS = ("sampler_name", "steps", "cfg", "scheduler", "seed", "denoise")


def fetch_ksampler_defaults(server, source_workflow):
    """Whatever of sampler_name/steps/cfg/scheduler/seed/denoise could be
    read from source_workflow's own KSampler node, live from `server` - an
    empty dict if the fetch/parse failed for any reason, letting the
    caller fall back to its own defaults. Shared by KSamplerDefaultsThread
    (the normal, non-blocking path) and a caller that needs a synchronous,
    guaranteed-fresh fetch right before it's used (see
    MainWindow._ksampler_defaults_for_current_workflow) - same logic
    either way, just a different thread."""
    try:
        template = load_live_template(server, source_workflow)
    except SystemExit:
        return {}
    except Exception:  # noqa: BLE001 - any fetch failure just means "no defaults available"
        return {}

    ksampler_id = find_ksampler_node_id(template)
    if not ksampler_id:
        return {}

    inputs = template[ksampler_id].get("inputs", {})
    # A KSampler input's value in API-format JSON is either a literal
    # (what we want) or a [node_id, output_index] connection reference -
    # e.g. seed fed by a separate Primitive/"Seed Everywhere" node,
    # common enough in real workflows. Only literals are usable as a
    # starting value; a connection reference isn't a number/string at
    # all and would blow up ModelConfigDialog's int()/float() handling
    # downstream, so filter it out here rather than there.
    return {
        k: inputs[k] for k in KSAMPLER_DEFAULT_KEYS
        if k in inputs and isinstance(inputs[k], (str, int, float))
    }


class KSamplerDefaultsThread(QThread):
    # Emits whatever of sampler_name/steps/cfg/scheduler/seed/denoise could
    # be read from the workflow's KSampler node - an empty dict if the
    # fetch/parse failed for any reason, letting the caller fall back to
    # its own defaults.
    result_ready = Signal(dict)

    def __init__(self, server, source_workflow, parent=None):
        super().__init__(parent)
        self.server = server
        self.source_workflow = source_workflow

    def run(self):
        self.result_ready.emit(fetch_ksampler_defaults(self.server, self.source_workflow))
