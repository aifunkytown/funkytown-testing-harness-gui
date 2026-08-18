"""Background fetch of the currently-referenced workflow's own KSampler
values (sampler/steps/cfg/scheduler), so the "Add Model" dialog can default
to whatever the workflow actually uses right now instead of arbitrary
numbers. Runs on a thread since it goes through the same live fetch+convert
as run_test.py (can take a few seconds, launches a headless browser) and
shouldn't freeze the window at startup or when the workflow selection
changes.
"""

from PySide6.QtCore import QThread, Signal

from funkytown_testing_harness.live_workflow import load_live_template
from funkytown_testing_harness.run_test import find_ksampler_node_id

KSAMPLER_DEFAULT_KEYS = ("sampler_name", "steps", "cfg", "scheduler")


class KSamplerDefaultsThread(QThread):
    # Emits whatever of sampler_name/steps/cfg/scheduler could be read from
    # the workflow's KSampler node - an empty dict if the fetch/parse failed
    # for any reason, letting the caller fall back to its own defaults.
    result_ready = Signal(dict)

    def __init__(self, server, source_workflow, parent=None):
        super().__init__(parent)
        self.server = server
        self.source_workflow = source_workflow

    def run(self):
        try:
            template = load_live_template(self.server, self.source_workflow)
        except SystemExit:
            self.result_ready.emit({})
            return
        except Exception:  # noqa: BLE001 - any fetch failure just means "no defaults available"
            self.result_ready.emit({})
            return

        ksampler_id = find_ksampler_node_id(template)
        if not ksampler_id:
            self.result_ready.emit({})
            return

        inputs = template[ksampler_id].get("inputs", {})
        self.result_ready.emit({k: inputs[k] for k in KSAMPLER_DEFAULT_KEYS if k in inputs})
