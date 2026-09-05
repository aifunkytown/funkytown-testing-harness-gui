"""Background check of whether Ollama and the configured ComfyUI server are
currently reachable, for the small status lights next to Settings in the
top bar. Runs on a thread since both checks are blocking network calls
(each with its own multi-second timeout) and would otherwise freeze the
window for as long as either takes - most noticeably on the periodic
recheck (see MainWindow._start_connectivity_poll), not just the one-time
check at startup.
"""

from PySide6.QtCore import QThread, Signal

from comfy_prompt_tools import clean_prompts
from funkytown_testing_harness_gui import comfy_client


def check_connectivity(server):
    """(ollama_ok, comfy_ok) - each independently False if unreachable
    rather than raising, so one being down never prevents reporting the
    other's real status."""
    ollama_ok = clean_prompts.check_ollama_running()
    comfy_ok = comfy_client.check_server_reachable(server)
    return ollama_ok, comfy_ok


class ConnectivityCheckThread(QThread):
    # Emits (ollama_ok, comfy_ok)
    result_ready = Signal(bool, bool)

    def __init__(self, server, parent=None):
        super().__init__(parent)
        self.server = server

    def run(self):
        ollama_ok, comfy_ok = check_connectivity(self.server)
        self.result_ready.emit(ollama_ok, comfy_ok)
