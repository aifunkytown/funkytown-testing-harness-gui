"""Main window: pick a workflow (top, shared), then either build a
model-comparison config or a LoRA-weight-sweep config in the tabs below -
reusing funkytown_testing_harness.run_test.run() /
funkytown_testing_harness.lora_test.run() and live_workflow.py exactly as
their own CLIs do, so behavior is identical either way.
"""

import json
from pathlib import Path

import funkytown_testing_harness
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from funkytown_testing_harness.lora_test import run as run_lora_test
from funkytown_testing_harness.run_test import run as run_model_test
from funkytown_testing_harness_gui import comfy_client
from funkytown_testing_harness_gui.app_settings import load_settings, save_settings
from funkytown_testing_harness_gui.ksampler_defaults_thread import KSamplerDefaultsThread
from funkytown_testing_harness_gui.lora_weights_dialog import LoraWeightsDialog
from funkytown_testing_harness_gui.model_config_dialog import ModelConfigDialog
from funkytown_testing_harness_gui.runner_thread import TestRunnerThread
from funkytown_testing_harness_gui.settings_dialog import SettingsDialog

# Wherever funkytown_testing_harness actually resolved from (default sibling
# or a custom path from Settings) - that's where its configs/ folder lives.
HARNESS_ROOT = Path(funkytown_testing_harness.__file__).resolve().parent.parent
CONFIGS_DIR = HARNESS_ROOT / "configs"

# This GUI project's own root - for its own local run state, independent of
# the harness project.
GUI_PROJECT_ROOT = Path(__file__).resolve().parent.parent
GUI_MODEL_RUN_CONFIG_PATH = GUI_PROJECT_ROOT / "gui_last_model_run.json"
GUI_LORA_RUN_CONFIG_PATH = GUI_PROJECT_ROOT / "gui_last_lora_run.json"

MODELS_TAB_INDEX = 0
LORA_TAB_INDEX = 1


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("funkytown-testing-harness")
        self.resize(780, 780)

        self.settings = load_settings()
        self._models = {}  # model_name -> list[dict] (configs)
        self._loras = {}  # lora_name -> list[float] (weights)
        self._runner_thread = None
        self._ksampler_defaults = {}  # populated from the referenced workflow when possible
        self._defaults_thread = None

        self._build_menu_bar()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_top_bar())
        root.addWidget(self._build_workflow_group())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_models_tab(), "Models")
        self.tabs.addTab(self._build_lora_tab(), "LoRA")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self.run_button = QPushButton("Run Test")
        self.run_button.clicked.connect(self._on_run_clicked)
        root.addWidget(self.run_button)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        root.addWidget(QLabel("Log:"))
        root.addWidget(self.log_view, 1)

        self._refresh_workflow_list()
        self._refresh_model_dropdown()
        self._refresh_lora_dropdown()
        self._refresh_sampler_options()

        if not self.settings.get("comfyui_install_dir"):
            # Deferred so the main window is up and painted before a modal
            # dialog pops in front of it, rather than appearing mid-construction.
            QTimer.singleShot(0, self._first_run_prompt_install_dir)

    # ---- menu bar -------------------------------------------------------------

    def _build_menu_bar(self):
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction("&Save...", self._file_save)
        file_menu.addAction("&Import...", self._file_import)

    # ---- top bar (name, server status, settings) -------------------------

    def _build_top_bar(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Test name:"))
        self.name_edit = QLineEdit("model_testing")
        row.addWidget(self.name_edit, 1)

        self.server_label = QLabel()
        row.addWidget(self.server_label)

        settings_button = QPushButton("Settings...")
        settings_button.clicked.connect(self._open_settings)
        row.addWidget(settings_button)

        self._update_server_label()
        return row

    def _update_server_label(self):
        reachable = comfy_client.check_server_reachable(self.settings["server"])
        status = "reachable" if reachable else "NOT reachable"
        self.server_label.setText(f"Server: {self.settings['server']} ({status})")

    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.settings = dialog.settings
            self._update_server_label()
            self._refresh_workflow_list()
            self._refresh_model_dropdown()
            self._refresh_lora_dropdown()
            self._refresh_sampler_options()

    def _first_run_prompt_install_dir(self):
        """Runs once at startup while comfyui_install_dir isn't set yet (i.e.
        every launch until it is). Tries to infer it from a running ComfyUI
        server's own launch arguments and asks for confirmation; if that's
        not possible (or the guess is wrong), sends the user to Settings."""
        inferred = comfy_client.infer_comfyui_install_dir(self.settings["server"])
        if inferred:
            answer = QMessageBox.question(
                self,
                "ComfyUI installation folder",
                f"Detected ComfyUI installation folder:\n\n{inferred}\n\nIs this correct?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                self.settings["comfyui_install_dir"] = inferred
                save_settings(self.settings)
                self._refresh_workflow_list()
                return

        QMessageBox.information(
            self,
            "ComfyUI installation folder needed",
            "Set your ComfyUI installation folder so the workflow dropdown can find your saved workflows.",
        )
        self._open_settings()

    # ---- workflow group (shared by both tabs) -------------------------------

    def _build_workflow_group(self):
        group = QGroupBox("Workflow")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Source workflow:"))
        self.workflow_combo = QComboBox()
        self.workflow_combo.setEditable(True)
        self.workflow_combo.activated.connect(lambda _index: self._refresh_ksampler_defaults())
        row.addWidget(self.workflow_combo, 1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_workflow_list)
        row.addWidget(refresh_button)
        layout.addLayout(row)

        self.strip_loras_check = QCheckBox("Strip LoRAs (clear the Power Lora Loader node)")
        self.strip_loras_check.setToolTip("Models tab only - lora_test.py needs the LoRA slots to stay present.")
        layout.addWidget(self.strip_loras_check)

        layout.addWidget(QLabel("Positive prompt override (leave blank to use the workflow's own):"))
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setMaximumHeight(90)
        layout.addWidget(self.prompt_edit)

        return group

    def _refresh_workflow_list(self):
        current = self.workflow_combo.currentText()
        self.workflow_combo.clear()
        names = comfy_client.list_local_workflows(self.settings["comfyui_install_dir"])
        if not names:
            self.workflow_combo.addItem("")
            self._log("No workflows found - set the ComfyUI installation folder in Settings.")
        else:
            self.workflow_combo.addItems(names)
        if current:
            idx = self.workflow_combo.findText(current)
            if idx >= 0:
                self.workflow_combo.setCurrentIndex(idx)
            else:
                self.workflow_combo.setEditText(current)
        self._refresh_ksampler_defaults()

    def _refresh_ksampler_defaults(self):
        """Pull sampler/steps/cfg/scheduler from the currently-referenced
        workflow's own KSampler node, in the background, for use as the
        starting values in the "Add Model" dialog (Models tab only). Falls
        back to KSamplerConfigRow.FALLBACK_DEFAULTS if this fails or hasn't
        completed yet."""
        source_workflow = self.workflow_combo.currentText().strip()
        if not source_workflow:
            self._ksampler_defaults = {}
            return
        if self._defaults_thread is not None and self._defaults_thread.isRunning():
            # Don't drop the still-running thread's only Python reference by
            # reassigning self._defaults_thread out from under it - that can
            # get it garbage-collected mid-flight. Whichever of the two
            # requests finishes will still update _ksampler_defaults; the
            # workflow selector's own change already implies the user can
            # re-trigger a refresh (Refresh button, or picking it again).
            return
        self._defaults_thread = KSamplerDefaultsThread(self.settings["server"], source_workflow, self)
        self._defaults_thread.result_ready.connect(self._on_ksampler_defaults_ready)
        self._defaults_thread.start()

    def _on_ksampler_defaults_ready(self, defaults):
        self._ksampler_defaults = defaults
        if defaults:
            self._log(f"KSampler defaults from workflow: {defaults}")
        else:
            self._log("Could not read KSampler defaults from the workflow - new configs will start from "
                       "cfg=1, steps=8, euler, beta.")

    def _on_tab_changed(self, index):
        # strip_loras only applies to run_test.py - lora_test.py's
        # build_template() never reads it, and stripping would remove the
        # very slots a LoRA run needs to toggle.
        self.strip_loras_check.setEnabled(index == MODELS_TAB_INDEX)

    # ---- models tab -------------------------------------------------------

    def _build_models_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(
            "<b>Models to compare</b> (at least 2 required alone; at least 1 if the "
            "LoRA tab also has LoRAs added - see Run Test below)"
        ))

        row = QHBoxLayout()
        row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        row.addWidget(self.model_combo, 1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_model_dropdown)
        row.addWidget(refresh_button)
        add_button = QPushButton("Add to list")
        add_button.clicked.connect(self._on_add_model)
        row.addWidget(add_button)
        layout.addLayout(row)

        self.models_list = QListWidget()
        self.models_list.itemDoubleClicked.connect(lambda item: self._edit_model(item.text()))
        layout.addWidget(self.models_list, 1)

        buttons_row = QHBoxLayout()
        edit_button = QPushButton("Edit selected...")
        edit_button.clicked.connect(self._edit_selected_model)
        buttons_row.addWidget(edit_button)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_selected_model)
        buttons_row.addWidget(remove_button)
        layout.addLayout(buttons_row)

        return page

    def _refresh_model_dropdown(self):
        models = comfy_client.list_available_models(self.settings["server"])
        if not models:
            self._log("No models found - is ComfyUI running and reachable?")
        for combo in (self.model_combo, self.lora_model_combo):
            current = combo.currentText()
            combo.clear()
            combo.addItems(models)
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _refresh_sampler_options(self):
        self._sampler_names = comfy_client.list_sampler_names(self.settings["server"]) or ["euler"]
        self._schedulers = comfy_client.list_schedulers(self.settings["server"]) or ["normal"]

    def _on_add_model(self):
        model_name = self.model_combo.currentText().strip()
        if not model_name:
            return
        initial = self._models.get(model_name, [{}])
        dialog = ModelConfigDialog(
            model_name, self._sampler_names, self._schedulers, self,
            initial_configs=initial, defaults=self._ksampler_defaults,
        )
        if dialog.exec():
            self._models[model_name] = dialog.configs
            self._rebuild_models_list()

    def _edit_selected_model(self):
        item = self.models_list.currentItem()
        if item:
            self._edit_model(item.text())

    def _edit_model(self, list_text):
        model_name = list_text.split("  —")[0].strip()
        if model_name not in self._models:
            return
        dialog = ModelConfigDialog(
            model_name, self._sampler_names, self._schedulers, self,
            initial_configs=self._models[model_name], defaults=self._ksampler_defaults,
        )
        if dialog.exec():
            self._models[model_name] = dialog.configs
            self._rebuild_models_list()

    def _remove_selected_model(self):
        item = self.models_list.currentItem()
        if not item:
            return
        model_name = item.text().split("  —")[0].strip()
        self._models.pop(model_name, None)
        self._rebuild_models_list()

    def _rebuild_models_list(self):
        self.models_list.clear()
        for model_name, configs in self._models.items():
            n = len(configs)
            label = f"{model_name}  — {n} config{'s' if n != 1 else ''}"
            self.models_list.addItem(QListWidgetItem(label))

    def _build_model_config_dict(self):
        return {
            "name": self.name_edit.text().strip() or "model_testing",
            "source_workflow": self.workflow_combo.currentText().strip(),
            "strip_loras": self.strip_loras_check.isChecked(),
            "positive_prompt": self.prompt_edit.toPlainText().strip(),
            "server": self.settings["server"],
            "models": [
                {"model": model_name, "configs": configs}
                for model_name, configs in self._models.items()
            ],
        }

    # ---- lora tab -----------------------------------------------------------

    def _build_lora_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        row.addWidget(QLabel("Model (used only if the Models tab has no models added):"))
        self.lora_model_combo = QComboBox()
        row.addWidget(self.lora_model_combo, 1)
        refresh_model_button = QPushButton("Refresh")
        refresh_model_button.clicked.connect(self._refresh_model_dropdown)
        row.addWidget(refresh_model_button)
        layout.addLayout(row)

        self.combine_loras_check = QCheckBox(
            "Combine LoRAs (run every weight combination together, rather than one LoRA at a time)"
        )
        layout.addWidget(self.combine_loras_check)

        layout.addWidget(QLabel("<b>LoRAs to sweep</b>"))
        layout.addWidget(QLabel(
            "A LoRA must already exist as a slot in the workflow's Power Lora Loader\n"
            "node (added there via ComfyUI's \"+ Add Lora\" widget) - a slot can be\n"
            "toggled here but not created."
        ))

        lora_row = QHBoxLayout()
        lora_row.addWidget(QLabel("LoRA:"))
        self.lora_combo = QComboBox()
        lora_row.addWidget(self.lora_combo, 1)
        refresh_lora_button = QPushButton("Refresh")
        refresh_lora_button.clicked.connect(self._refresh_lora_dropdown)
        lora_row.addWidget(refresh_lora_button)
        add_lora_button = QPushButton("Add to list")
        add_lora_button.clicked.connect(self._on_add_lora)
        lora_row.addWidget(add_lora_button)
        layout.addLayout(lora_row)

        self.loras_list = QListWidget()
        self.loras_list.itemDoubleClicked.connect(lambda item: self._edit_lora(item.text()))
        layout.addWidget(self.loras_list, 1)

        buttons_row = QHBoxLayout()
        edit_button = QPushButton("Edit selected...")
        edit_button.clicked.connect(self._edit_selected_lora)
        buttons_row.addWidget(edit_button)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_selected_lora)
        buttons_row.addWidget(remove_button)
        layout.addLayout(buttons_row)

        return page

    def _refresh_lora_dropdown(self):
        self.lora_combo.clear()
        loras = comfy_client.list_available_loras(self.settings["server"])
        if not loras:
            self._log("No LoRAs found - is ComfyUI running and reachable?")
        else:
            self.lora_combo.addItems(loras)

    def _on_add_lora(self):
        lora_name = self.lora_combo.currentText().strip()
        if not lora_name:
            return
        initial = self._loras.get(lora_name, [1.0])
        dialog = LoraWeightsDialog(lora_name, self, initial_weights=initial)
        if dialog.exec():
            self._loras[lora_name] = dialog.weights
            self._rebuild_loras_list()

    def _edit_selected_lora(self):
        item = self.loras_list.currentItem()
        if item:
            self._edit_lora(item.text())

    def _edit_lora(self, list_text):
        lora_name = list_text.split("  —")[0].strip()
        if lora_name not in self._loras:
            return
        dialog = LoraWeightsDialog(lora_name, self, initial_weights=self._loras[lora_name])
        if dialog.exec():
            self._loras[lora_name] = dialog.weights
            self._rebuild_loras_list()

    def _remove_selected_lora(self):
        item = self.loras_list.currentItem()
        if not item:
            return
        lora_name = item.text().split("  —")[0].strip()
        self._loras.pop(lora_name, None)
        self._rebuild_loras_list()

    def _rebuild_loras_list(self):
        self.loras_list.clear()
        for lora_name, weights in self._loras.items():
            n = len(weights)
            label = f"{lora_name}  — {n} weight{'s' if n != 1 else ''}"
            self.loras_list.addItem(QListWidgetItem(label))

    def _build_lora_config_dict(self):
        return {
            "name": self.name_edit.text().strip() or "lora_testing",
            "source_workflow": self.workflow_combo.currentText().strip(),
            "model": self.lora_model_combo.currentText().strip(),
            "positive_prompt": self.prompt_edit.toPlainText().strip(),
            "combine_loras": self.combine_loras_check.isChecked(),
            "server": self.settings["server"],
            "loras": [
                {"lora": lora_name, "weights": weights}
                for lora_name, weights in self._loras.items()
            ],
        }

    def _build_lora_config_dict_for(self, models):
        """Same shape _build_lora_config_dict produces, but with an explicit
        models list - used for the combined mode (Models list x LoRA combos)."""
        return {
            "name": self.name_edit.text().strip() or "lora_testing",
            "source_workflow": self.workflow_combo.currentText().strip(),
            "models": models,
            "positive_prompt": self.prompt_edit.toPlainText().strip(),
            "combine_loras": self.combine_loras_check.isChecked(),
            "server": self.settings["server"],
            "loras": [
                {"lora": lora_name, "weights": weights}
                for lora_name, weights in self._loras.items()
            ],
        }

    # ---- unified run (Models tab and/or LoRA tab, whichever are populated) ----

    def _build_effective_run(self):
        """Returns (config, run_func) for whichever tab(s) are populated, or
        (None, None) with a warning already shown if it can't run yet."""
        models_on = bool(self._models)
        lora_on = bool(self._loras)

        if not models_on and not lora_on:
            QMessageBox.warning(self, "Nothing to run", "Add at least one model (Models tab) or LoRA (LoRA tab) to run a test.")
            return None, None
        if not self.workflow_combo.currentText().strip():
            QMessageBox.warning(self, "No workflow selected", "Pick a source workflow first.")
            return None, None

        if models_on and lora_on:
            config = self._build_lora_config_dict_for(list(self._models.keys()))
            if not config["positive_prompt"]:
                del config["positive_prompt"]
            return config, run_lora_test

        if models_on:
            if len(self._models) < 2:
                QMessageBox.warning(self, "Not enough models", "Add at least 2 models to compare.")
                return None, None
            config = self._build_model_config_dict()
            if not config["positive_prompt"]:
                del config["positive_prompt"]
            return config, run_model_test

        # lora_on only
        if not self.lora_model_combo.currentText().strip():
            QMessageBox.warning(self, "No model selected", "Pick a model for the LoRA test first.")
            return None, None
        config = self._build_lora_config_dict()
        if not config["positive_prompt"]:
            del config["positive_prompt"]
        return config, run_lora_test

    def _confirm_run(self, config):
        dialog = QDialog(self)
        dialog.setWindowTitle("Confirm test run")
        dialog.setMinimumSize(520, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("About to queue this test job:"))

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(config, indent=2))
        text.setFont(QFont("Consolas", 9))
        layout.addWidget(text, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Run")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        return dialog.exec() == QDialog.Accepted

    def _on_run_clicked(self):
        config, run_func = self._build_effective_run()
        if config is None:
            return
        if not self._confirm_run(config):
            return

        run_config_path = GUI_LORA_RUN_CONFIG_PATH if run_func is run_lora_test else GUI_MODEL_RUN_CONFIG_PATH
        run_config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        self.log_view.clear()
        self.run_button.setEnabled(False)
        self.run_button.setText("Running...")

        self._runner_thread = TestRunnerThread(run_func, run_config_path, self)
        self._runner_thread.log_line.connect(self._log)
        self._runner_thread.finished_ok.connect(self._on_run_finished_ok)
        self._runner_thread.finished_error.connect(self._on_run_finished_error)
        self._runner_thread.start()

    def _on_run_finished_ok(self):
        self.run_button.setEnabled(True)
        self.run_button.setText("Run Test")
        self._log("Done.")

    def _on_run_finished_error(self, message):
        self.run_button.setEnabled(True)
        self.run_button.setText("Run Test")
        self._log(f"ERROR: {message}")
        QMessageBox.critical(self, "Run failed", message)

    # ---- File menu: Save / Import (combined Models + LoRA state) --------------

    def _build_combined_config_dict(self):
        """The full editing-session state for both tabs together - this is
        the GUI's own save format, not necessarily what gets hand to
        run_test.py/lora_test.py directly (that happens separately, per-run,
        in _build_effective_run/_on_run_clicked)."""
        config = {
            "name": self.name_edit.text().strip() or "test",
            "source_workflow": self.workflow_combo.currentText().strip(),
            "positive_prompt": self.prompt_edit.toPlainText().strip(),
            "server": self.settings["server"],
        }
        if self._models:
            config["strip_loras"] = self.strip_loras_check.isChecked()
            config["models"] = [
                {"model": model_name, "configs": configs}
                for model_name, configs in self._models.items()
            ]
        if self._loras:
            config["combine_loras"] = self.combine_loras_check.isChecked()
            config["loras"] = [
                {"lora": lora_name, "weights": weights}
                for lora_name, weights in self._loras.items()
            ]
            lora_model = self.lora_model_combo.currentText().strip()
            if lora_model:
                config["lora_model"] = lora_model
        return config

    def _file_save(self):
        if not self._models and not self._loras:
            QMessageBox.critical(
                self, "Nothing to save",
                "Add at least one model (Models tab) or LoRA (LoRA tab) before saving.",
            )
            return

        config = self._build_combined_config_dict()
        if not config["positive_prompt"]:
            del config["positive_prompt"]

        CONFIGS_DIR.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save test config", str(CONFIGS_DIR / "combined-testing-config.json"), "JSON files (*.json)"
        )
        if not path:
            return
        Path(path).write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._log(f"Saved config to {path}")

    def _file_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import test config", str(CONFIGS_DIR), "JSON files (*.json)")
        if not path:
            return
        config = json.loads(Path(path).read_text(encoding="utf-8"))

        if "name" in config:
            self.name_edit.setText(config["name"])
        if "source_workflow" in config:
            self.workflow_combo.setEditText(config["source_workflow"])
        if "positive_prompt" in config:
            self.prompt_edit.setPlainText(config["positive_prompt"])

        # Each side only touches its own tab's data, and only if the
        # imported file actually has that key - so importing an
        # old-style single-schema file (or a combined one missing one
        # side) combines into whatever's already on the other tab instead
        # of wiping it out.
        if "models" in config:
            self._models = {m["model"]: m.get("configs") or [{}] for m in config["models"]}
            self._rebuild_models_list()
            if "strip_loras" in config:
                self.strip_loras_check.setChecked(bool(config["strip_loras"]))

        if "loras" in config:
            self._loras = {entry["lora"]: entry.get("weights") or [1.0] for entry in config["loras"]}
            self._rebuild_loras_list()
            if "combine_loras" in config:
                self.combine_loras_check.setChecked(bool(config["combine_loras"]))
            lora_model = config.get("lora_model") or config.get("model")
            if lora_model:
                if self.lora_model_combo.findText(lora_model) < 0:
                    self.lora_model_combo.addItem(lora_model)
                self.lora_model_combo.setCurrentText(lora_model)

        self._log(f"Imported config from {path}")

    # ---- shared log -----------------------------------------------------------

    def _log(self, line):
        self.log_view.appendPlainText(line)
