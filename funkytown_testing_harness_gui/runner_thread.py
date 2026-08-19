"""Runs a harness run() function (funkytown_testing_harness.run_test.run or
.lora_test.run - anything with the same run(config_path) signature) on a
background thread so the UI stays responsive (fetching/converting the
workflow and queuing can take a few seconds), and captures its print()-based
progress output into the log panel instead of the real console. run() calls
sys.exit() on error conditions (e.g. fewer than 2 models present, or a
missing model) - that raises SystemExit, which is caught here and reported
through the same signal as any other failure rather than killing the thread
silently.
"""

import io
import sys
import threading

from PySide6.QtCore import QThread, Signal

_stdout_lock = threading.Lock()


class _LineEmittingStream(io.TextIOBase):
    def __init__(self, emit):
        super().__init__()
        self._emit = emit
        self._buffer = ""

    def write(self, text):
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)
        return len(text)

    def flush(self):
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""


class TestRunnerThread(QThread):
    log_line = Signal(str)
    finished_ok = Signal()
    finished_error = Signal(str)

    def __init__(self, run_func, config_path, parent=None):
        super().__init__(parent)
        self.run_func = run_func
        self.config_path = config_path

    def run(self):
        stream = _LineEmittingStream(self.log_line.emit)
        # Only one test run happens at a time in this UI (the Run button is
        # disabled while running), but guard the global stdout swap anyway.
        with _stdout_lock:
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = stream
            sys.stderr = stream
            try:
                self.run_func(self.config_path)
            except SystemExit as e:
                stream.flush()
                self.finished_error.emit(str(e.code) if e.code else "Aborted.")
                return
            except Exception as e:  # noqa: BLE001 - surface any failure to the UI rather than crashing the thread
                stream.flush()
                self.finished_error.emit(f"{type(e).__name__}: {e}")
                return
            finally:
                stream.flush()
                sys.stdout, sys.stderr = old_stdout, old_stderr
        self.finished_ok.emit()
