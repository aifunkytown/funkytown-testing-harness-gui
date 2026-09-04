"""Main window: pick a workflow (top, shared), then either build a
model-comparison config or a LoRA-weight-sweep config in the tabs below -
reusing funkytown_testing_harness.run_test.run() /
funkytown_testing_harness.lora_test.run() and live_workflow.py exactly as
their own CLIs do, so behavior is identical either way.
"""

import csv
import datetime
import json
import os
import re
import shutil
from pathlib import Path

import funkytown_testing_harness
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from funkytown_testing_harness import comparison_grid
from funkytown_testing_harness.lora_test import run as run_lora_test
from funkytown_testing_harness.run_test import run as run_model_test
from comfy_prompt_tools import clean_prompts, extract_and_clean, extract_image_prompts, generate_prompt_variations, rerun_prompts_comfyui
from comfy_prompt_tools.clean_prompts import MODEL as CLEAN_PROMPTS_DEFAULT_MODEL
from comfy_prompt_tools.local_config import load_named_list, local_path_for
from funkytown_testing_harness_gui import comfy_client
from funkytown_testing_harness_gui.app_settings import load_settings, save_settings
from funkytown_testing_harness_gui.ksampler_defaults_thread import KSamplerDefaultsThread
from funkytown_testing_harness_gui.generations_csv_prompts_dialog import GenerationsCsvPromptsDialog
from funkytown_testing_harness_gui.lora_weights_dialog import LoraWeightsDialog
from funkytown_testing_harness_gui.model_config_dialog import ModelConfigDialog
from funkytown_testing_harness_gui.prompts_dialog import PromptsDialog
from funkytown_testing_harness_gui.runner_thread import TestRunnerThread
from funkytown_testing_harness_gui.settings_dialog import SettingsDialog
from funkytown_testing_harness_gui.theme import apply_theme
from funkytown_testing_harness_gui.thumbnail_loader_thread import ThumbnailLoaderThread
from funkytown_testing_harness_gui.variations_prompts_dialog import VariationsPromptsDialog

# Wherever funkytown_testing_harness actually resolved from (default sibling
# or a custom path from Settings) - that's where its configs/ (and runs/)
# folder lives.
HARNESS_ROOT = Path(funkytown_testing_harness.__file__).resolve().parent.parent
CONFIGS_DIR = HARNESS_ROOT / "configs"
RUNS_DIR = HARNESS_ROOT / "runs"

# This GUI project's own root - for its own local run state, independent of
# the harness project.
GUI_PROJECT_ROOT = Path(__file__).resolve().parent.parent
GUI_MODEL_RUN_CONFIG_PATH = GUI_PROJECT_ROOT / "gui_last_model_run.json"
GUI_LORA_RUN_CONFIG_PATH = GUI_PROJECT_ROOT / "gui_last_lora_run.json"
GUI_VARIATIONS_RUN_CONFIG_PATH = GUI_PROJECT_ROOT / "gui_last_variations_run.json"
GUI_QUEUE_VARIATIONS_RUN_CONFIG_PATH = GUI_PROJECT_ROOT / "gui_last_queue_variations_run.json"
GUI_GENERATIONS_RUN_CONFIG_PATH = GUI_PROJECT_ROOT / "gui_last_generations_run.json"
GUI_GENERATIONS_CLEAN_CSV_CONFIG_PATH = GUI_PROJECT_ROOT / "gui_last_generations_clean_csv_run.json"

MODELS_TAB_INDEX = 0
LORA_TAB_INDEX = 1

# run_test.py/lora_test.py/rerun_prompts_comfyui.py all name their log
# "<name>_<started-at:%Y%m%d_%H%M%S>.csv" - matches that trailing timestamp
# so the Results tab can order runs by when each was actually started.
RUN_LOG_TIMESTAMP_RE = re.compile(r"_(\d{8}_\d{6})$")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("funkytown-testing-harness")
        self.resize(780, 780)

        self.settings = load_settings()
        self._models = {}  # model_name -> list[dict] (configs)
        self._loras = {}  # lora_name -> list[float] (weights)
        self._prompts = []  # Testing tab's prompt list - see Prompts... popup
        self._results_gallery_anchor_row = None  # last plain-clicked row, for Shift+click range-check
        self._runner_thread = None
        self._ksampler_defaults = {}  # populated from the referenced workflow when possible
        self._defaults_thread = None
        self._thumbnail_loaders = []  # in-flight ThumbnailLoaderThreads - kept alive here until each finishes
        self._generations_thumbnail_loaders = []  # same, for the Generations tab's own gallery
        self._generations_thread = None
        self._generations_pending_results_source = ("directory", "")  # set right before each generations run - see _start_generations_thread
        self._last_variations_output_paths = []  # set on each successful Generate Variations run
        self._last_test_config_path = None  # set on each successful Save Test.../Import Test...

        self._build_menu_bar()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.outer_tabs = QTabWidget()
        self.outer_tabs.addTab(self._build_testing_tab(), "Testing")
        self.outer_tabs.addTab(self._build_generations_tab(), "Generations")
        self.outer_tabs.addTab(self._build_variations_tab(), "Variations")
        self.outer_tabs.addTab(self._build_results_tab(), "Results")
        root.addWidget(self.outer_tabs, 1)

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
        file_menu.addAction("&Save Test...", self._file_save)
        file_menu.addAction("&Import Test...", self._file_import)

        settings_menu = self.menuBar().addMenu("&Settings")
        self.hide_explicit_action = settings_menu.addAction("Hide Explicit")
        self.hide_explicit_action.setCheckable(True)
        self.hide_explicit_action.setChecked(bool(self.settings.get("hide_explicit_aspects", True)))
        self.hide_explicit_action.setToolTip(
            "Hide aspects prompt_aspect_vocab.json marks as explicit (_explicit_aspects) "
            "from the Variations tab's aspect checklist."
        )
        self.hide_explicit_action.toggled.connect(self._on_hide_explicit_toggled)

        self.dark_mode_action = settings_menu.addAction("Dark Mode")
        self.dark_mode_action.setCheckable(True)
        self.dark_mode_action.setChecked(bool(self.settings.get("dark_mode", True)))
        self.dark_mode_action.toggled.connect(self._on_dark_mode_toggled)

    def _on_hide_explicit_toggled(self, checked):
        self.settings["hide_explicit_aspects"] = checked
        save_settings(self.settings)
        self._populate_variations_aspect_list()

    def _on_dark_mode_toggled(self, checked):
        self.settings["dark_mode"] = checked
        save_settings(self.settings)
        apply_theme(QApplication.instance(), checked)

    # ---- outer "Testing" tab: everything that existed before the Variations tab ----

    def _build_testing_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addLayout(self._build_top_bar())
        layout.addWidget(self._build_workflow_group())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_models_tab(), "Model")
        self.tabs.addTab(self._build_lora_tab(), "LoRA")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)

        run_row = QHBoxLayout()
        self.run_button = QPushButton("Run Test")
        self.run_button.clicked.connect(self._on_run_clicked)
        run_row.addWidget(self.run_button, 1)
        save_test_button = QPushButton("Save Test...")
        save_test_button.clicked.connect(self._file_save)
        run_row.addWidget(save_test_button, 1)
        layout.addLayout(run_row)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self._add_collapsible_log(page, layout, self.log_view)

        return page

    def _add_collapsible_log(self, page, layout, log_view):
        """Adds a collapsible "Log" section: a small clickable arrow that
        toggles log_view's visibility, collapsed by default.

        log_view is a normal member of `layout` (previously a floating
        overlay on `page` specifically to avoid resizing the window - but
        that meant expanding it could get clipped by the window's own
        bottom edge with no way to see the rest, which is worse than the
        window growing to fit it). Being a real layout member means
        expanding it grows the window to make room, same as any other
        newly-shown widget; collapsing it shrinks the window back down."""
        toggle_button = QToolButton()
        toggle_button.setArrowType(Qt.RightArrow)
        toggle_button.setText("Log")
        toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle_button.setCheckable(True)
        toggle_button.setChecked(False)
        toggle_button.setAutoRaise(True)
        layout.addWidget(toggle_button)

        log_view.setMinimumHeight(220)
        log_view.setVisible(False)
        layout.addWidget(log_view, 1)

        def on_toggled(checked):
            toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
            log_view.setVisible(checked)

        toggle_button.toggled.connect(on_toggled)

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

        strip_row = QHBoxLayout()
        self.use_default_loras_check = QCheckBox("Use Default LoRAs (keep the workflow's own Power Lora Loader setup)")
        self.use_default_loras_check.setToolTip(
            "Model tab only - lora_test.py needs the LoRA slots to stay present.\n\n"
            "Checked: leave the workflow's Power Lora Loader node exactly as it "
            "already is. Unchecked (default): clear it for this test's queued "
            "workflow only. Either way, this has no effect on "
            "rerun_prompts_comfyui.py's own keyword-based routing (lora_rules.json "
            "/ lora_rules.local.json) - see \"Edit LoRA Rules...\"."
        )
        strip_row.addWidget(self.use_default_loras_check)
        strip_row.addStretch(1)
        lora_rules_button = QPushButton("Edit LoRA Rules...")
        lora_rules_button.setToolTip(
            "View and edit rerun_prompts_comfyui.py's current keyword -> LoRA "
            "rules. These apply whenever a prompt is rerun through that script, "
            "regardless of the Use Default LoRAs setting above."
        )
        lora_rules_button.clicked.connect(self._edit_lora_rules)
        strip_row.addWidget(lora_rules_button)
        layout.addLayout(strip_row)

        layout.addWidget(QLabel(
            "Note: Use Default LoRAs above only affects this test's own queued "
            "workflow. If a prompt from this run gets exported and later rerun "
            "via rerun_prompts_comfyui.py, its keyword rules (\"Edit LoRA "
            "Rules...\") can still turn a matching LoRA on based on the prompt text."
        ))

        layout.addWidget(QLabel("<b>Prompt</b>"))
        prompts_button_row = QHBoxLayout()
        edit_prompts_button = QPushButton("Prompts...")
        edit_prompts_button.setToolTip(
            "Leave empty to use the workflow's own prompt, add one to "
            "override it, or two or more for a sweep - every model/LoRA "
            "combo in this run is tested against each one. Load prompts "
            "from a CSV below, or add/remove them directly in the popup; "
            "removing one never touches the source CSV file."
        )
        edit_prompts_button.clicked.connect(self._on_edit_prompts_clicked)
        prompts_button_row.addWidget(edit_prompts_button)
        self.prompts_summary_label = QLabel()
        prompts_button_row.addWidget(self.prompts_summary_label, 1)
        layout.addLayout(prompts_button_row)
        self._update_prompts_summary_label()

        prompts_csv_row = QHBoxLayout()
        prompts_csv_row.addWidget(QLabel("Load from CSV:"))
        self.prompts_csv_edit = QLineEdit()
        prompts_csv_row.addWidget(self.prompts_csv_edit, 1)
        browse_prompts_button = QPushButton("Browse...")
        browse_prompts_button.clicked.connect(self._on_browse_prompts_csv)
        prompts_csv_row.addWidget(browse_prompts_button)
        clear_prompts_csv_button = QPushButton("Clear")
        clear_prompts_csv_button.setToolTip("Clear the CSV path and Min/Max row - the prompt list itself is left as-is (edit it via Prompts... instead).")
        clear_prompts_csv_button.clicked.connect(self._on_clear_prompts_csv_clicked)
        prompts_csv_row.addWidget(clear_prompts_csv_button)
        layout.addLayout(prompts_csv_row)

        prompts_row_row = QHBoxLayout()
        prompts_row_row.addWidget(QLabel("Min row:"))
        self.prompts_row_min_spin = QSpinBox()
        self.prompts_row_min_spin.setRange(1, 1)
        self.prompts_row_min_spin.setEnabled(False)
        prompts_row_row.addWidget(self.prompts_row_min_spin)
        prompts_row_row.addWidget(QLabel("Max row:"))
        self.prompts_row_max_spin = QSpinBox()
        self.prompts_row_max_spin.setRange(1, 1)
        self.prompts_row_max_spin.setEnabled(False)
        prompts_row_row.addWidget(self.prompts_row_max_spin)
        self.prompts_edited_label = QLabel("edited")
        self.prompts_edited_label.setStyleSheet("color: red; font-weight: bold;")
        self.prompts_edited_label.setVisible(False)
        self.prompts_edited_label.setToolTip(
            "The prompt list above no longer matches a fresh pull of this CSV/row range."
        )
        prompts_row_row.addWidget(self.prompts_edited_label)
        prompts_row_row.addStretch(1)
        layout.addLayout(prompts_row_row)

        self._last_loaded_csv_prompts = None
        self.prompts_csv_edit.textChanged.connect(self._on_prompts_csv_changed)
        self.prompts_row_min_spin.valueChanged.connect(self._on_prompts_range_changed)
        self.prompts_row_max_spin.valueChanged.connect(self._on_prompts_range_changed)

        return group

    def _load_prompts_from_csv(self):
        """Refresh self._prompts to match a fresh pull of the current CSV +
        Min/Max row selection. Always overwrites the list - changing which
        rows you're pointed at is an explicit "give me these instead"
        action, unlike editing via the Prompts... popup (which trips the
        "edited" indicator instead of ever being silently overwritten)."""
        csv_path = self.prompts_csv_edit.text().strip()
        if not csv_path or not Path(csv_path).is_file() or not self.prompts_row_min_spin.isEnabled():
            return
        try:
            row_numbers = generate_prompt_variations.parse_row_range(
                self._row_range_arg(self.prompts_row_min_spin, self.prompts_row_max_spin)
            )
            resolved = self._extract_csv_prompt_rows(csv_path, row_numbers)
        except Exception:
            return

        prompts = [row_text for _row_num, row_text, _label in resolved if row_text]
        self._prompts = prompts
        self._last_loaded_csv_prompts = list(prompts)
        self._update_prompts_summary_label()
        self.prompts_edited_label.setVisible(False)

    def _refresh_prompts_edited_state(self):
        """Recompute whether self._prompts still matches a fresh pull of
        the currently-configured CSV + row range, without touching
        self._prompts itself - used after File > Import Test... so the
        "edited" indicator reflects reality even though the list was
        populated directly from the imported prompts, not via the normal
        auto-load path."""
        csv_path = self.prompts_csv_edit.text().strip()
        if not csv_path or not Path(csv_path).is_file() or not self.prompts_row_min_spin.isEnabled():
            self._last_loaded_csv_prompts = None
            self.prompts_edited_label.setVisible(False)
            return
        try:
            row_numbers = generate_prompt_variations.parse_row_range(
                self._row_range_arg(self.prompts_row_min_spin, self.prompts_row_max_spin)
            )
            resolved = self._extract_csv_prompt_rows(csv_path, row_numbers)
        except Exception:
            self._last_loaded_csv_prompts = None
            self.prompts_edited_label.setVisible(False)
            return
        fresh_prompts = [row_text for _row_num, row_text, _label in resolved if row_text]
        self._last_loaded_csv_prompts = fresh_prompts
        self.prompts_edited_label.setVisible(self._prompts != fresh_prompts)

    def _update_prompts_summary_label(self):
        n = len(self._prompts)
        if n == 0:
            self.prompts_summary_label.setText("(none - uses the workflow's own prompt)")
        elif n == 1:
            preview = self._prompts[0]
            if len(preview) > 60:
                preview = preview[:57] + "..."
            self.prompts_summary_label.setText(f'1 prompt - "{preview}"')
        else:
            self.prompts_summary_label.setText(f"{n} prompts (sweep)")

    def _on_edit_prompts_clicked(self):
        dialog = PromptsDialog(self._prompts, self)
        if dialog.exec():
            self._prompts = dialog.prompts
            self._update_prompts_summary_label()
            self._refresh_prompts_edited_state()

    def _prompt_lines(self):
        """Non-empty prompts currently held for the Testing tab's run."""
        return [text for text in self._prompts if text.strip()]

    def _single_prompt_text(self):
        return self._prompts[0] if self._prompts else ""

    def _edit_lora_rules(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit LoRA Rules")
        dialog.setMinimumSize(560, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "Keyword -> LoRA rules for rerun_prompts_comfyui.py. Keywords are "
            "comma-separated and matched case-insensitively against prompt text - "
            "if any keyword in a row matches, that row's LoRA is turned on at the "
            "given strength. Saving writes these to a gitignored "
            "lora_rules.local.json next to lora_rules.json in comfy-prompt-tools, "
            "so they're never committed."
        ))

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Keywords (comma-separated)", "LoRA filename", "Strength"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        # A single click starts editing immediately, rather than needing a
        # double-click or F2 first - Qt's default item delegate already
        # commits on Enter or on the editor losing focus (clicking away).
        table.itemClicked.connect(table.editItem)
        for rule in rerun_prompts_comfyui.LORA_RULES:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(", ".join(rule["keywords"])))
            table.setItem(row, 1, QTableWidgetItem(rule["lora"]))
            table.setItem(row, 2, QTableWidgetItem(str(rule["strength"])))
        layout.addWidget(table, 1)

        buttons_row = QHBoxLayout()
        add_button = QPushButton("Add rule")
        add_button.clicked.connect(lambda: self._add_lora_rule_row(table))
        buttons_row.addWidget(add_button)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(lambda: self._remove_selected_lora_rule_rows(table))
        buttons_row.addWidget(remove_button)
        layout.addLayout(buttons_row)

        dialog_buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        dialog_buttons.rejected.connect(dialog.reject)

        def try_save():
            rules, errors = self._parse_lora_rules_table(table)
            if errors:
                QMessageBox.warning(dialog, "Invalid LoRA rules", "\n".join(errors))
                return
            dialog._saved_rules = rules
            dialog.accept()

        dialog_buttons.accepted.connect(try_save)
        layout.addWidget(dialog_buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        local_path = local_path_for(rerun_prompts_comfyui.LORA_RULES_PATH)
        local_path.write_text(json.dumps({"rules": dialog._saved_rules}, indent=2), encoding="utf-8")
        rerun_prompts_comfyui.LORA_RULES = load_named_list(rerun_prompts_comfyui.LORA_RULES_PATH, "rules", "lora")
        self._log(f"Saved LoRA rules to {local_path}")

    def _add_lora_rule_row(self, table):
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(""))
        table.setItem(row, 1, QTableWidgetItem(""))
        table.setItem(row, 2, QTableWidgetItem("1.0"))

    def _remove_selected_lora_rule_rows(self, table):
        for row in sorted({index.row() for index in table.selectedIndexes()}, reverse=True):
            table.removeRow(row)

    def _parse_lora_rules_table(self, table):
        rules = []
        errors = []
        for row in range(table.rowCount()):
            keywords_text = (table.item(row, 0).text() if table.item(row, 0) else "").strip()
            lora = (table.item(row, 1).text() if table.item(row, 1) else "").strip()
            strength_text = (table.item(row, 2).text() if table.item(row, 2) else "").strip()

            if not keywords_text and not lora and not strength_text:
                continue  # skip a fully-blank row rather than erroring on it

            keywords = [k.strip() for k in keywords_text.split(",") if k.strip()]
            if not keywords:
                errors.append(f"Row {row + 1}: at least one keyword is required.")
                continue
            if not lora:
                errors.append(f"Row {row + 1}: LoRA filename is required.")
                continue
            try:
                strength = float(strength_text)
            except ValueError:
                errors.append(f"Row {row + 1}: strength must be a number, got '{strength_text}'.")
                continue

            rules.append({"keywords": keywords, "lora": lora, "strength": strength})
        return rules, errors

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
        self.use_default_loras_check.setEnabled(index == MODELS_TAB_INDEX)

    # ---- models tab -------------------------------------------------------

    def _build_models_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(
            "<b>Model(s)</b> - the model(s) any test uses. At least 2 required to "
            "compare models against each other; 1 is enough if the LoRA tab also has "
            "LoRAs added (every model here is then run against every LoRA combination)."
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
        current = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        idx = self.model_combo.findText(current)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

    def _refresh_sampler_options(self):
        self._sampler_names = comfy_client.list_sampler_names(self.settings["server"]) or ["euler"]
        self._schedulers = comfy_client.list_schedulers(self.settings["server"]) or ["normal"]

    def _open_model_config_dialog(self, model_name, initial_configs):
        """Shared by _on_add_model/_edit_model - wrapped in a try/except
        that surfaces the actual error instead of the dialog silently never
        appearing, since ModelConfigDialog's starting values are built from
        live-fetched workflow data (self._ksampler_defaults) that can't be
        fully validated ahead of time."""
        try:
            return ModelConfigDialog(
                model_name, self._sampler_names, self._schedulers, self,
                initial_configs=initial_configs, defaults=self._ksampler_defaults,
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Couldn't open model config",
                f"{type(e).__name__}: {e}\n\nThis is a bug - please report it with this message.",
            )
            return None

    def _on_add_model(self):
        model_name = self.model_combo.currentText().strip()
        if not model_name:
            return
        initial = self._models.get(model_name, [{}])
        dialog = self._open_model_config_dialog(model_name, initial)
        if dialog is not None and dialog.exec():
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
        dialog = self._open_model_config_dialog(model_name, self._models[model_name])
        if dialog is not None and dialog.exec():
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

    def _build_model_config_dict(self, prompts=None):
        config = {
            "name": self.name_edit.text().strip() or "model_testing",
            "source_workflow": self.workflow_combo.currentText().strip(),
            "strip_loras": not self.use_default_loras_check.isChecked(),
            "server": self.settings["server"],
            "models": [
                {"model": model_name, "configs": configs}
                for model_name, configs in self._models.items()
            ],
        }
        if prompts:
            config["positive_prompts"] = prompts
        else:
            config["positive_prompt"] = self._single_prompt_text()
        return config

    # ---- lora tab -----------------------------------------------------------

    def _build_lora_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(
            "Runs against whichever model(s) are on the Model tab - add one there first."
        ))

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

    def _build_lora_config_dict_for(self, models, prompts=None):
        """A lora_test.py-shaped config using the Model tab's list - the sole
        source of model selection for any LoRA run now."""
        config = {
            "name": self.name_edit.text().strip() or "lora_testing",
            "source_workflow": self.workflow_combo.currentText().strip(),
            "models": models,
            "combine_loras": self.combine_loras_check.isChecked(),
            "server": self.settings["server"],
            "loras": [
                {"lora": lora_name, "weights": weights}
                for lora_name, weights in self._loras.items()
            ],
        }
        if prompts:
            config["positive_prompts"] = prompts
        else:
            config["positive_prompt"] = self._single_prompt_text()
        return config

    # ---- unified run (Models tab and/or LoRA tab, whichever are populated) ----

    def _build_effective_run(self):
        """Returns (config, run_func) for whichever tab(s) are populated, or
        (None, None) with a warning already shown if it can't run yet."""
        models_on = bool(self._models)
        lora_on = bool(self._loras)

        if not models_on and not lora_on:
            QMessageBox.warning(self, "Nothing to run", "Add at least one model (Model tab) or LoRA (LoRA tab) to run a test.")
            return None, None
        if not self.workflow_combo.currentText().strip():
            QMessageBox.warning(self, "No workflow selected", "Pick a source workflow first.")
            return None, None

        prompt_lines = self._prompt_lines()
        prompts = prompt_lines if len(prompt_lines) >= 2 else None

        if lora_on:
            if not models_on:
                QMessageBox.warning(self, "No model selected", "Add at least 1 model on the Model tab first.")
                return None, None
            config = self._build_lora_config_dict_for(list(self._models.keys()), prompts)
            if not config.get("positive_prompt"):
                config.pop("positive_prompt", None)
            return config, run_lora_test

        # models_on only
        if len(self._models) < 2:
            QMessageBox.warning(self, "Not enough models", "Add at least 2 models to compare.")
            return None, None
        config = self._build_model_config_dict(prompts)
        if not config.get("positive_prompt"):
            config.pop("positive_prompt", None)
        return config, run_model_test

    def _confirm_json(self, title, config, description="About to submit this job:", ok_text="Run"):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(520, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(description))

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(config, indent=2))
        text.setFont(QFont("Consolas", 9))
        layout.addWidget(text, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(ok_text)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        return dialog.exec() == QDialog.Accepted

    def _confirm_run(self, config):
        return self._confirm_json("Confirm test run", config, "About to queue this test job:", "Run")

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
        self._refresh_results_list()

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
            "server": self.settings["server"],
        }
        prompt_lines = self._prompt_lines()
        if len(prompt_lines) >= 2:
            config["positive_prompts"] = prompt_lines
        else:
            config["positive_prompt"] = self._single_prompt_text()
        # Purely informational, not authoritative - lets File > Import Test...
        # re-populate the CSV picker for further editing later. The
        # "positive_prompt(s)" above always reflects self._prompts' actual
        # current content, edited or not.
        if self.prompts_csv_edit.text().strip():
            config["positive_prompts_csv"] = self.prompts_csv_edit.text().strip()
            config["positive_prompts_min_row"] = self.prompts_row_min_spin.value()
            config["positive_prompts_max_row"] = self.prompts_row_max_spin.value()
        if self._models:
            config["strip_loras"] = not self.use_default_loras_check.isChecked()
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
        return config

    def _suggested_test_filename(self):
        """Default filename for Save Test... when there's no previous
        saved/imported path to default to instead - the selected models
        plus today's date, e.g. "modelA_modelB_2026-08-29.json"."""
        model_stems = [Path(m).stem for m in self._models.keys()]
        if len(model_stems) > 3:
            models_part = "_".join(model_stems[:3]) + f"_and{len(model_stems) - 3}more"
        elif model_stems:
            models_part = "_".join(model_stems)
        else:
            models_part = "test"
        return f"{models_part}_{datetime.date.today().isoformat()}.json"

    def _file_save(self):
        if not self._models and not self._loras:
            QMessageBox.critical(
                self, "Nothing to save",
                "Add at least one model (Model tab) or LoRA (LoRA tab) before saving.",
            )
            return

        config = self._build_combined_config_dict()
        if not config.get("positive_prompt"):
            config.pop("positive_prompt", None)

        CONFIGS_DIR.mkdir(exist_ok=True)
        default_path = self._last_test_config_path or (CONFIGS_DIR / self._suggested_test_filename())
        path, _ = QFileDialog.getSaveFileName(
            self, "Save test config", str(default_path), "JSON files (*.json)"
        )
        if not path:
            return
        Path(path).write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._last_test_config_path = Path(path)
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
        if "positive_prompts_csv" in config:
            # Restore the CSV/row-range picker fields silently (informational
            # only) - _suppress_prompt_autoload keeps this from clobbering
            # self._prompts, set from "positive_prompt(s)" just below.
            self._suppress_prompt_autoload = True
            self.prompts_csv_edit.setText(config["positive_prompts_csv"])
            if "positive_prompts_min_row" in config:
                self.prompts_row_min_spin.setValue(config["positive_prompts_min_row"])
            if "positive_prompts_max_row" in config:
                self.prompts_row_max_spin.setValue(config["positive_prompts_max_row"])
            self._suppress_prompt_autoload = False
        if "positive_prompts" in config:
            self._prompts = list(config["positive_prompts"])
        elif "positive_prompt" in config:
            self._prompts = [config["positive_prompt"]] if config["positive_prompt"] else []
        elif "positive_prompts_csv" in config:
            # Older save format (from before the Prompts... popup existed)
            # stored only the CSV/range, never a resolved prompt list -
            # fall back to resolving it fresh now (using the CSV/range just
            # restored above) so importing an old file doesn't silently
            # leave self._prompts empty.
            self._load_prompts_from_csv()
        self._update_prompts_summary_label()
        self._refresh_prompts_edited_state()

        # Each side only touches its own tab's data, and only if the
        # imported file actually has that key - so importing an
        # old-style single-schema file (or a combined one missing one
        # side) combines into whatever's already on the other tab instead
        # of wiping it out.
        if "models" in config:
            self._models = {m["model"]: m.get("configs") or [{}] for m in config["models"]}
            self._rebuild_models_list()
            if "strip_loras" in config:
                self.use_default_loras_check.setChecked(not bool(config["strip_loras"]))

        if "loras" in config:
            self._loras = {entry["lora"]: entry.get("weights") or [1.0] for entry in config["loras"]}
            self._rebuild_loras_list()
            if "combine_loras" in config:
                self.combine_loras_check.setChecked(bool(config["combine_loras"]))
            # Older lora_test.py configs used a single "model" key - there's
            # no dropdown to hold that any more, so fold it into the Model
            # tab's list instead of dropping it (unless a "models" list was
            # already present above and took care of it).
            if "models" not in config:
                model_name = (config.get("model") or "").strip()
                if model_name and model_name not in self._models:
                    self._models[model_name] = [{}]
                    self._rebuild_models_list()

        self._last_test_config_path = Path(path)
        self._log(f"Imported config from {path}")

    # ---- shared log -----------------------------------------------------------

    def _log(self, line):
        self.log_view.appendPlainText(line)

    # ---- Variations tab: comfy_prompt_tools.generate_prompt_variations --------

    def _populate_ollama_model_dropdown(self):
        """Lists locally-pulled Ollama models (via generate_prompt_variations.
        list_ollama_models(), which just hits Ollama's own /api/tags) so the
        dropdown reflects whatever's actually installed - falling back to just
        DEFAULT_MODEL if Ollama isn't reachable or has nothing pulled yet. The
        combo box stays editable regardless, so a model not in the list can
        still be typed in by hand."""
        models = generate_prompt_variations.list_ollama_models()
        if generate_prompt_variations.DEFAULT_MODEL not in models:
            models = [generate_prompt_variations.DEFAULT_MODEL] + models
        self.variations_model_combo.addItems(models)
        self.variations_model_combo.setCurrentText(generate_prompt_variations.DEFAULT_MODEL)

    def _build_variations_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(
            "Generates variations of one prompt row from a CSV (via "
            "comfy_prompt_tools.generate_prompt_variations), using a local Ollama model."
        ))

        csv_row = QHBoxLayout()
        csv_row.addWidget(QLabel("CSV file:"))
        self.variations_csv_edit = QLineEdit()
        csv_row.addWidget(self.variations_csv_edit, 1)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse_variations_csv)
        csv_row.addWidget(browse_button)
        layout.addLayout(csv_row)

        single_prompt_row = QHBoxLayout()
        single_prompt_row.addWidget(QLabel("Single prompt (no CSV needed):"))
        self.variations_single_prompt_edit = QLineEdit()
        self.variations_single_prompt_edit.setPlaceholderText("Type or paste a single prompt...")
        self.variations_single_prompt_edit.setToolTip(
            "Only used when no CSV file is chosen above - lets you generate "
            "variations of one ad-hoc prompt without needing a CSV at all."
        )
        single_prompt_row.addWidget(self.variations_single_prompt_edit, 1)
        layout.addLayout(single_prompt_row)

        row_row = QHBoxLayout()
        row_row.addWidget(QLabel("Min row:"))
        self.variations_row_min_spin = QSpinBox()
        self.variations_row_min_spin.setRange(1, 1)
        self.variations_row_min_spin.setEnabled(False)
        row_row.addWidget(self.variations_row_min_spin)
        row_row.addWidget(QLabel("Max row:"))
        self.variations_row_max_spin = QSpinBox()
        self.variations_row_max_spin.setRange(1, 1)
        self.variations_row_max_spin.setEnabled(False)
        row_row.addWidget(self.variations_row_max_spin)
        self.variations_prompts_edited_label = QLabel("edited")
        self.variations_prompts_edited_label.setStyleSheet("color: red; font-weight: bold;")
        self.variations_prompts_edited_label.setVisible(False)
        self.variations_prompts_edited_label.setToolTip(
            "The prompts list below no longer matches a fresh pull of this CSV/row range."
        )
        row_row.addWidget(self.variations_prompts_edited_label)
        row_row.addStretch(1)
        layout.addLayout(row_row)

        self._variations_current_prompts = {}  # row_num -> text, populated from CSV
        self._last_loaded_variations_prompts = None
        self.variations_csv_edit.textChanged.connect(self._on_variations_csv_changed)
        self.variations_row_min_spin.valueChanged.connect(self._on_variations_range_changed)
        self.variations_row_max_spin.valueChanged.connect(self._on_variations_range_changed)

        prompts_button_row = QHBoxLayout()
        self.variations_prompts_button = QPushButton("Prompts...")
        self.variations_prompts_button.setToolTip(
            "Browse the CSV rows' source text (Cleaned Prompt if present, "
            "otherwise Positive Prompt) - edit a row's text to override it, "
            "or remove one to skip that row. Neither ever touches the "
            "source CSV file."
        )
        self.variations_prompts_button.clicked.connect(self._on_edit_variations_prompts_clicked)
        prompts_button_row.addWidget(self.variations_prompts_button)
        self.variations_prompts_summary_label = QLabel()
        prompts_button_row.addWidget(self.variations_prompts_summary_label, 1)
        layout.addLayout(prompts_button_row)
        self._update_variations_prompts_summary_label()

        mode_row = QHBoxLayout()
        self.variations_named_radio = QRadioButton("Named aspect(s)")
        self.variations_named_radio.setChecked(True)
        self.variations_named_radio.toggled.connect(self._on_variations_mode_changed)
        self.variations_random_radio = QRadioButton("Random aspects:")
        mode_group = QButtonGroup(page)
        mode_group.addButton(self.variations_named_radio)
        mode_group.addButton(self.variations_random_radio)
        mode_row.addWidget(self.variations_named_radio)
        mode_row.addWidget(self.variations_random_radio)
        self.variations_random_spin = QSpinBox()
        self.variations_random_spin.setRange(1, 50)
        self.variations_random_spin.setValue(3)
        self.variations_random_spin.setEnabled(False)
        mode_row.addWidget(self.variations_random_spin)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        layout.addWidget(QLabel(
            "Aspects (from prompt_aspect_vocab.json - check one or more):"
        ))
        self.variations_aspect_list = QListWidget()
        self._populate_variations_aspect_list()
        layout.addWidget(self.variations_aspect_list, 1)

        extra_row = QHBoxLayout()
        extra_row.addWidget(QLabel("Extra aspect(s) not in the list (comma-separated):"))
        self.variations_extra_aspect_edit = QLineEdit()
        extra_row.addWidget(self.variations_extra_aspect_edit, 1)
        layout.addLayout(extra_row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Count:"))
        self.variations_count_spin = QSpinBox()
        self.variations_count_spin.setRange(1, 100)
        self.variations_count_spin.setValue(5)
        settings_row.addWidget(self.variations_count_spin)
        settings_row.addWidget(QLabel("Ollama model:"))
        self.variations_model_combo = QComboBox()
        self.variations_model_combo.setEditable(True)  # in case Ollama's unreachable or the wanted model isn't pulled yet
        self._populate_ollama_model_dropdown()
        settings_row.addWidget(self.variations_model_combo, 1)
        layout.addLayout(settings_row)

        generate_row = QHBoxLayout()
        self.variations_generate_button = QPushButton("Generate Variations")
        self.variations_generate_button.clicked.connect(self._on_generate_variations_clicked)
        generate_row.addWidget(self.variations_generate_button, 1)
        self.variations_queue_button = QPushButton("Queue Generated Variations")
        self.variations_queue_button.setEnabled(False)
        self.variations_queue_button.setToolTip(
            "Submits the CSV file(s) the most recent successful Generate Variations "
            "run wrote, to ComfyUI via rerun_prompts_comfyui.py - using the Testing "
            "tab's Source workflow and Settings' ComfyUI server."
        )
        self.variations_queue_button.clicked.connect(self._on_queue_variations_clicked)
        generate_row.addWidget(self.variations_queue_button, 1)
        layout.addLayout(generate_row)

        self.variations_log_view = QPlainTextEdit()
        self.variations_log_view.setReadOnly(True)
        self.variations_log_view.setMaximumBlockCount(5000)
        self._add_collapsible_log(page, layout, self.variations_log_view)

        return page

    def _populate_variations_aspect_list(self):
        self.variations_aspect_list.clear()
        vocab, _random_exclude, _multi_select, explicit_aspects = generate_prompt_variations.load_vocab(
            generate_prompt_variations.DEFAULT_VOCAB_PATH
        )
        hide_explicit = bool(self.settings.get("hide_explicit_aspects", True))
        for aspect_name in sorted(vocab):
            if hide_explicit and aspect_name in explicit_aspects:
                continue
            label = aspect_name + (" (explicit)" if aspect_name in explicit_aspects else "")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, aspect_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.variations_aspect_list.addItem(item)

    def _on_variations_mode_changed(self, _checked):
        named_mode = self.variations_named_radio.isChecked()
        self.variations_aspect_list.setEnabled(named_mode)
        self.variations_extra_aspect_edit.setEnabled(named_mode)
        self.variations_random_spin.setEnabled(not named_mode)

    def _csv_browse_default_dir(self):
        """Where a CSV file picker should open by default when its field is
        currently empty - ComfyUI's own output folder, since that's where
        prompt CSVs (from extract_image_prompts.py et al) typically live;
        falls back to funkytown-testing-harness's configs/ if no ComfyUI
        installation folder is set in Settings yet."""
        comfyui_install_dir = self.settings.get("comfyui_install_dir")
        if comfyui_install_dir:
            return str(Path(comfyui_install_dir) / "output")
        return str(CONFIGS_DIR)

    def _on_browse_variations_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose prompt CSV", self.variations_csv_edit.text() or self._csv_browse_default_dir(), "CSV files (*.csv)"
        )
        if path:
            self.variations_csv_edit.setText(path)

    def _update_row_spinboxes_for_csv(self, csv_path_text, min_spin, max_spin, enable_button=None):
        """Shared by the Variations tab and the Testing tab's prompt CSV
        picker: re-read a CSV's row count and set Min/Max row spinbox
        bounds/defaults to the full range - 1 to the last data row -
        disabling everything if the file's missing/invalid or has no data
        rows. Returns the row count."""
        row_count = 0
        if csv_path_text and Path(csv_path_text).is_file():
            try:
                with open(csv_path_text, newline="", encoding="utf-8") as f:
                    row_count = sum(1 for _ in csv.DictReader(f))
            except OSError:
                row_count = 0

        for spin in (min_spin, max_spin):
            spin.setEnabled(row_count > 0)
        if row_count > 0:
            min_spin.setRange(1, row_count)
            max_spin.setRange(1, row_count)
            min_spin.setValue(1)
            max_spin.setValue(row_count)

        if enable_button is not None:
            enable_button.setEnabled(row_count > 0)
        return row_count

    def _row_range_arg(self, min_spin, max_spin):
        """Min/Max row spinbox values as the "100" or "100-105" string form
        generate_prompt_variations.parse_row_range() expects."""
        lo, hi = min_spin.value(), max_spin.value()
        if lo > hi:
            lo, hi = hi, lo
        return str(lo) if lo == hi else f"{lo}-{hi}"

    def _extract_csv_prompt_rows(self, csv_path, row_numbers):
        """Returns a list of (row_num, text, source_label) for each row
        number - text/source_label are None if that row has neither Cleaned
        Prompt nor Positive Prompt text. Same source-text preference as
        generate_prompt_variations.run_batch: Cleaned Prompt if the CSV has
        that column and it's non-empty for the row, otherwise Positive
        Prompt. Raises ValueError if any row number is out of range."""
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        bad_rows = [r for r in row_numbers if r < 1 or r > len(rows)]
        if bad_rows:
            raise ValueError(f"Row(s) {', '.join(map(str, bad_rows))} out of range (CSV has {len(rows)} data row(s)).")

        cleaned_col = next((c for c in (rows[0].keys() if rows else []) if "cleaned" in c.lower()), None)

        results = []
        for row_num in row_numbers:
            source_row = rows[row_num - 1]
            cleaned_text = (source_row.get(cleaned_col) or "").strip() if cleaned_col else ""
            positive_text = (source_row.get("Positive Prompt") or "").strip()
            if cleaned_text:
                results.append((row_num, cleaned_text, "Cleaned Prompt"))
            elif positive_text:
                results.append((row_num, positive_text, "Positive Prompt"))
            else:
                results.append((row_num, None, None))
        return results

    def _on_variations_csv_changed(self, _text=None):
        csv_text = self.variations_csv_edit.text().strip()
        self._update_row_spinboxes_for_csv(
            csv_text,
            self.variations_row_min_spin, self.variations_row_max_spin,
        )
        # The single-prompt field is only meaningful when there's no CSV to
        # supply rows instead - disable it (rather than clearing it) so a
        # value typed earlier isn't lost if the CSV field gets cleared again.
        self.variations_single_prompt_edit.setEnabled(not bool(csv_text))
        self._load_variations_prompts()

    def _on_variations_range_changed(self, _value=None):
        self._load_variations_prompts()

    def _variations_row_arg(self):
        return self._row_range_arg(self.variations_row_min_spin, self.variations_row_max_spin)

    def _load_variations_prompts(self):
        """Refresh self._variations_current_prompts to match a fresh pull of
        the current CSV + Min/Max row selection - always overwrites it, same
        rationale as the Testing tab's _load_prompts_from_csv. Rows with no
        resolvable prompt text are omitted (nothing meaningful to generate
        variations from)."""
        csv_path = self.variations_csv_edit.text().strip()
        if not csv_path or not Path(csv_path).is_file() or not self.variations_row_min_spin.isEnabled():
            self._variations_current_prompts = {}
            self._last_loaded_variations_prompts = None
            self.variations_prompts_edited_label.setVisible(False)
            self._update_variations_prompts_summary_label()
            return
        try:
            row_numbers = generate_prompt_variations.parse_row_range(self._variations_row_arg())
            resolved = self._extract_csv_prompt_rows(csv_path, row_numbers)
        except Exception:
            self._variations_current_prompts = {}
            self._last_loaded_variations_prompts = None
            self.variations_prompts_edited_label.setVisible(False)
            self._update_variations_prompts_summary_label()
            return

        prompts = {row_num: text for row_num, text, _source_label in resolved if text}
        self._variations_current_prompts = prompts
        self._last_loaded_variations_prompts = dict(prompts)
        self.variations_prompts_edited_label.setVisible(False)
        self._update_variations_prompts_summary_label()

    def _update_variations_prompts_summary_label(self):
        n = len(self._variations_current_prompts)
        self.variations_prompts_button.setEnabled(n > 0)
        if n:
            self.variations_prompts_summary_label.setText(f"{n} prompt(s) loaded")
        else:
            self.variations_prompts_summary_label.setText("(load a CSV above to browse/edit its prompts)")

    def _on_edit_variations_prompts_clicked(self):
        ordered = sorted(self._variations_current_prompts.items())
        dialog = VariationsPromptsDialog(ordered, self)
        if dialog.exec():
            self._variations_current_prompts = dialog.current_prompts
            self._update_variations_prompts_summary_label()
            self._refresh_variations_edited_state()

    def _refresh_variations_edited_state(self):
        if self._last_loaded_variations_prompts is None:
            self.variations_prompts_edited_label.setVisible(False)
            return
        self.variations_prompts_edited_label.setVisible(
            self._variations_current_prompts != self._last_loaded_variations_prompts
        )

    def _on_browse_prompts_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose prompt CSV", self.prompts_csv_edit.text() or self._csv_browse_default_dir(), "CSV files (*.csv)"
        )
        if path:
            self.prompts_csv_edit.setText(path)

    def _on_prompts_csv_changed(self, _text=None):
        self._update_row_spinboxes_for_csv(
            self.prompts_csv_edit.text().strip(),
            self.prompts_row_min_spin, self.prompts_row_max_spin,
        )
        if not getattr(self, "_suppress_prompt_autoload", False):
            self._load_prompts_from_csv()

    def _on_prompts_range_changed(self, _value=None):
        if not getattr(self, "_suppress_prompt_autoload", False):
            self._load_prompts_from_csv()

    def _on_clear_prompts_csv_clicked(self):
        """Clears the CSV path, resets Min/Max row back to disabled, and
        empties the prompt list itself - a full reset back to "no CSV
        loaded", not just detaching the list from its source."""
        self.prompts_csv_edit.clear()  # -> _on_prompts_csv_changed disables the row spinboxes
        self.prompts_row_min_spin.setRange(1, 1)
        self.prompts_row_min_spin.setValue(1)
        self.prompts_row_max_spin.setRange(1, 1)
        self.prompts_row_max_spin.setValue(1)
        self._prompts = []
        self._last_loaded_csv_prompts = None
        self.prompts_edited_label.setVisible(False)
        self._update_prompts_summary_label()

    def _write_adhoc_prompt_csv(self, text):
        """Writes a single-row CSV so a manually-typed prompt (no CSV
        loaded) can flow through the exact same generate_prompt_variations.
        run_batch() path as a CSV-backed one - lands its "Variations"
        output under configs/Variations/, a predictable, discoverable
        location instead of a scattered temp directory."""
        CONFIGS_DIR.mkdir(exist_ok=True)
        adhoc_path = CONFIGS_DIR / "adhoc_prompt.csv"
        with open(adhoc_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["File Name", "Positive Prompt"])
            writer.writerow(["adhoc_prompt", text])
        return str(adhoc_path)

    def _build_variations_config(self):
        csv_path = self.variations_csv_edit.text().strip()
        prompt_overrides = None

        if not csv_path:
            single_prompt = self.variations_single_prompt_edit.text().strip()
            if not single_prompt:
                QMessageBox.warning(self, "No prompt", "Choose a CSV file, or type/paste a single prompt.")
                return None
            csv_path = self._write_adhoc_prompt_csv(single_prompt)
            rows = [1]
        else:
            if not Path(csv_path).is_file():
                QMessageBox.warning(self, "CSV not found", f"File not found:\n{csv_path}")
                return None
            if not self.variations_row_min_spin.isEnabled():
                QMessageBox.warning(self, "No rows", "The CSV file has no data rows, or hasn't loaded yet.")
                return None

            current_prompts = self._variations_current_prompts
            if not current_prompts:
                QMessageBox.warning(self, "No prompts", "The prompts list is empty - adjust the row range above, or it has no rows left.")
                return None

            baseline = self._last_loaded_variations_prompts or {}
            prompt_overrides = {
                row_num: text for row_num, text in current_prompts.items()
                if baseline.get(row_num) != text
            }
            rows = sorted(current_prompts)

        config = {
            "csv_path": csv_path,
            "rows": rows,
            "count": self.variations_count_spin.value(),
            "model": self.variations_model_combo.currentText().strip() or generate_prompt_variations.DEFAULT_MODEL,
        }
        if prompt_overrides:
            config["prompt_overrides"] = prompt_overrides

        if self.variations_named_radio.isChecked():
            chosen = [
                self.variations_aspect_list.item(i).data(Qt.UserRole)
                for i in range(self.variations_aspect_list.count())
                if self.variations_aspect_list.item(i).checkState() == Qt.Checked
            ]
            extra = [a.strip() for a in self.variations_extra_aspect_edit.text().split(",") if a.strip()]
            aspects = chosen + extra
            if not aspects:
                QMessageBox.warning(
                    self, "No aspect chosen",
                    "Check at least one aspect, or type one in the extra-aspects field.",
                )
                return None
            config["aspect"] = ", ".join(aspects)
        else:
            config["random_aspects"] = self.variations_random_spin.value()

        return config

    def _aspect_values_for_confirm(self, config):
        """Preview-only lookup (never written to the actual run config) -
        for any named, vocab-controlled aspect the config is about to use,
        its full list of possible values, so the confirm dialog shows what
        the model can actually pick from."""
        aspect_arg = config.get("aspect")
        if not aspect_arg:
            return {}
        vocab, _random_exclude, _multi_select, _explicit_aspects = generate_prompt_variations.load_vocab(
            generate_prompt_variations.DEFAULT_VOCAB_PATH
        )
        aspects = generate_prompt_variations.parse_aspects(aspect_arg)
        return {a: vocab[a.lower()] for a in aspects if a.lower() in vocab and vocab[a.lower()]}

    def _on_generate_variations_clicked(self):
        config = self._build_variations_config()
        if config is None:
            return

        preview = dict(config)
        aspect_values = self._aspect_values_for_confirm(config)
        if aspect_values:
            preview["aspect_values"] = aspect_values

        if not self._confirm_json("Confirm variations job", preview, "About to generate variations for:", "Generate"):
            return

        GUI_VARIATIONS_RUN_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._pending_variations_output_paths = self._expected_variations_output_paths(config)

        self.variations_log_view.clear()
        self.variations_generate_button.setEnabled(False)
        self.variations_generate_button.setText("Generating...")

        self._variations_thread = TestRunnerThread(generate_prompt_variations.run, GUI_VARIATIONS_RUN_CONFIG_PATH, self)
        self._variations_thread.log_line.connect(self.variations_log_view.appendPlainText)
        self._variations_thread.finished_ok.connect(self._on_variations_finished_ok)
        self._variations_thread.finished_error.connect(self._on_variations_finished_error)
        self._variations_thread.start()

    def _expected_variations_output_paths(self, config):
        """Same output-path formula as generate_prompt_variations.run_batch()
        (only reachable there via a stdout "Wrote ... to ..." line, which
        isn't something to depend on for hooking up Queue Generated
        Variations) - recomputed here from the same csv_path/row inputs, so
        it stays correct if that formula ever changes."""
        csv_path = Path(config["csv_path"])
        row_numbers = config["rows"]
        variations_dir = csv_path.parent / "Variations"
        return [variations_dir / f"{csv_path.stem}_row{row_num}_variations.csv" for row_num in row_numbers]

    def _on_variations_finished_ok(self):
        self.variations_generate_button.setEnabled(True)
        self.variations_generate_button.setText("Generate Variations")
        self.variations_log_view.appendPlainText("Done.")
        self._last_variations_output_paths = self._pending_variations_output_paths
        self.variations_queue_button.setEnabled(True)

    def _on_variations_finished_error(self, message):
        self.variations_generate_button.setEnabled(True)
        self.variations_generate_button.setText("Generate Variations")
        self.variations_log_view.appendPlainText(f"ERROR: {message}")
        QMessageBox.critical(self, "Generation failed", message)

    def _on_queue_variations_clicked(self):
        if not self._last_variations_output_paths:
            QMessageBox.warning(self, "Nothing to queue", "Run Generate Variations successfully first.")
            return

        workflow_name = self.workflow_combo.currentText().strip()
        if not workflow_name:
            QMessageBox.warning(self, "No workflow selected", "Pick a source workflow on the Testing tab first.")
            return
        comfyui_install_dir = self.settings.get("comfyui_install_dir")
        if not comfyui_install_dir:
            QMessageBox.warning(self, "ComfyUI folder not set", "Set your ComfyUI installation folder in Settings first.")
            return
        workflow_path = Path(comfyui_install_dir) / "user" / "default" / "workflows" / workflow_name
        if not workflow_path.is_file():
            QMessageBox.warning(self, "Workflow not found", f"File not found:\n{workflow_path}")
            return

        missing = [p for p in self._last_variations_output_paths if not p.is_file()]
        if missing:
            QMessageBox.warning(
                self, "Output file(s) missing",
                "File(s) from the last Generate Variations run weren't found (maybe "
                "moved or deleted):\n" + "\n".join(str(p) for p in missing),
            )
            return

        RUNS_DIR.mkdir(exist_ok=True)
        log_path = RUNS_DIR / f"variations_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv"

        config = {
            "csv_paths": [str(p) for p in self._last_variations_output_paths],
            "workflow": str(workflow_path),
            "server": self.settings["server"],
            "log": str(log_path),
        }

        if not self._confirm_json("Confirm queue job", config, "About to queue these file(s) to ComfyUI:", "Queue"):
            return

        GUI_QUEUE_VARIATIONS_RUN_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")

        self.variations_log_view.appendPlainText("\n--- Queuing generated variations ---")
        self.variations_queue_button.setEnabled(False)
        self.variations_queue_button.setText("Queuing...")

        self._queue_variations_thread = TestRunnerThread(rerun_prompts_comfyui.run, GUI_QUEUE_VARIATIONS_RUN_CONFIG_PATH, self)
        self._queue_variations_thread.log_line.connect(self.variations_log_view.appendPlainText)
        self._queue_variations_thread.finished_ok.connect(self._on_queue_variations_finished_ok)
        self._queue_variations_thread.finished_error.connect(self._on_queue_variations_finished_error)
        self._queue_variations_thread.start()

    def _on_queue_variations_finished_ok(self):
        self.variations_queue_button.setEnabled(True)
        self.variations_queue_button.setText("Queue Generated Variations")
        self.variations_log_view.appendPlainText("Done.")
        self._refresh_results_list()

    def _on_queue_variations_finished_error(self, message):
        self.variations_queue_button.setEnabled(True)
        self.variations_queue_button.setText("Queue Generated Variations")
        self.variations_log_view.appendPlainText(f"ERROR: {message}")
        QMessageBox.critical(self, "Queue failed", message)

    # ---- Results tab: browse previous runs' output images ---------------------

    def _build_results_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(
            "Every logged run - Model/LoRA test runs, and Variations runs "
            "that were queued to ComfyUI - newest first. Select one to see "
            "its output images on the right (not the OS file browser); "
            "double-click a thumbnail to view it full size. A still-in-"
            "progress run is fine to select - this never polls ComfyUI, it "
            "just shows whatever's on disk right now."
        ))

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.select_all_runs_check = QCheckBox("Select All")
        self.select_all_runs_check.stateChanged.connect(self._on_select_all_runs_toggled)
        left_layout.addWidget(self.select_all_runs_check)

        self.results_list = QListWidget()
        # NoFocus stops Qt from auto-selecting row 0 the moment the list
        # becomes visible (its normal behavior for a focusable, populated
        # view) - nothing should be selected/shown until the user actually
        # clicks a run. Mouse clicks still select items fine either way.
        self.results_list.setFocusPolicy(Qt.NoFocus)
        self.results_list.currentItemChanged.connect(self._on_results_selection_changed)
        self.results_list.itemChanged.connect(self._on_results_run_item_changed)
        left_layout.addWidget(self.results_list, 1)

        buttons_row = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_results_list)
        buttons_row.addWidget(refresh_button)
        delete_button = QPushButton("Delete selected")
        delete_button.setToolTip("Deletes the checked run(s)' logs and their output images. Cannot be undone.")
        delete_button.clicked.connect(self._on_delete_selected_result)
        buttons_row.addWidget(delete_button)
        self.create_grid_button = QPushButton("Create Grid")
        self.create_grid_button.setEnabled(False)
        self.create_grid_button.setToolTip(
            "Builds a labeled side-by-side comparison image from whichever "
            "images are checked in the gallery on the right (one column "
            "per model/LoRA combo, up to 10 per image - more spill into "
            "additional numbered files) - check at least 2 first."
        )
        self.create_grid_button.clicked.connect(self._on_create_grid_clicked)
        buttons_row.addWidget(self.create_grid_button)
        left_layout.addLayout(buttons_row)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.select_all_images_check = QCheckBox("Select All")
        self.select_all_images_check.stateChanged.connect(self._on_select_all_images_toggled)
        right_layout.addWidget(self.select_all_images_check)

        self.results_loading_label = QLabel("Loading images...")
        self.results_loading_label.setVisible(False)
        right_layout.addWidget(self.results_loading_label)

        # Grid cell is deliberately larger than the icon itself (rather than
        # relying on setSpacing(), which only takes one uniform value) so
        # the gap between thumbnails can differ horizontally vs vertically -
        # 1px between columns, 5px between rows.
        results_icon_size = QSize(440, 440)
        self.results_images_view = QListWidget()
        self.results_images_view.setViewMode(QListWidget.IconMode)
        self.results_images_view.setIconSize(results_icon_size)
        self.results_images_view.setGridSize(QSize(results_icon_size.width() + 1, results_icon_size.height() + 5))
        self.results_images_view.setResizeMode(QListWidget.Adjust)
        self.results_images_view.setMovement(QListWidget.Static)
        self.results_images_view.setUniformItemSizes(True)
        self.results_images_view.itemClicked.connect(self._on_results_image_clicked)
        self.results_images_view.itemDoubleClicked.connect(self._on_open_full_image)
        right_layout.addWidget(self.results_images_view, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([450, 900])  # left (run list) panel ~50% wider than a bare default
        layout.addWidget(splitter, 1)
        self._results_splitter = splitter

        self._refresh_results_list()

        return page

    def _refresh_results_list(self):
        """Re-scans runs/ for the list on the left. Re-selects whichever run
        was previously current (if it's still there) instead of dropping
        back to no selection - Refresh should just bring the image panel on
        the right up to date, not lose your place."""
        previously_selected = self.results_list.currentItem()
        previously_selected_log = previously_selected.data(Qt.UserRole) if previously_selected else None

        self._suppress_select_all_runs_toggle = True
        self.select_all_runs_check.setChecked(False)  # every run starts unchecked after a refresh
        self._suppress_select_all_runs_toggle = False

        self.results_list.clear()
        self.results_images_view.clear()
        if not RUNS_DIR.is_dir():
            return
        log_paths = sorted(RUNS_DIR.glob("*.csv"), key=self._run_log_sort_key, reverse=True)
        for log_path in log_paths:
            kind, count = self._read_run_log_summary(log_path)
            noun = "image(s)" if kind == "Generations" else "queued"
            item = QListWidgetItem(f"{log_path.stem}   ({kind}, {count} {noun})")
            item.setData(Qt.UserRole, str(log_path))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.results_list.addItem(item)
            if previously_selected_log is not None and str(log_path) == previously_selected_log:
                self.results_list.setCurrentItem(item)

    def _on_select_all_runs_toggled(self, _state):
        if getattr(self, "_suppress_select_all_runs_toggle", False):
            return
        check_state = Qt.Checked if self.select_all_runs_check.isChecked() else Qt.Unchecked
        self._suppress_run_item_changed = True
        for i in range(self.results_list.count()):
            self.results_list.item(i).setCheckState(check_state)
        self._suppress_run_item_changed = False

    def _on_results_run_item_changed(self, _item):
        """Keeps Select All in sync with the individual run checkboxes -
        checked only once every run in the list is checked, same pattern
        as the image gallery's own Select All."""
        if getattr(self, "_suppress_run_item_changed", False):
            return
        count = self.results_list.count()
        all_checked = count > 0 and all(
            self.results_list.item(i).checkState() == Qt.Checked for i in range(count)
        )
        self._suppress_select_all_runs_toggle = True
        self.select_all_runs_check.setChecked(all_checked)
        self._suppress_select_all_runs_toggle = False

    def _checked_results_runs(self):
        return [
            Path(self.results_list.item(i).data(Qt.UserRole))
            for i in range(self.results_list.count())
            if self.results_list.item(i).checkState() == Qt.Checked
        ]

    def _run_log_sort_key(self, log_path):
        """Sorts by the run's actual start time, embedded in its filename
        (see RUN_LOG_TIMESTAMP_RE) - falls back to the file's own mtime for
        anything that doesn't match. Using the embedded start time instead
        of mtime matters because a run's log is rewritten throughout (see
        the checkpointing in run_test.py etc.), so mtime reflects whenever
        it was last written to rather than when the run actually started -
        those can disagree, e.g. a long-running test that's still going
        when a later, shorter one both starts and finishes."""
        match = RUN_LOG_TIMESTAMP_RE.search(log_path.stem)
        if match:
            try:
                return datetime.datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
            except ValueError:
                pass
        return datetime.datetime.fromtimestamp(log_path.stat().st_mtime)

    def _read_run_log_summary(self, log_path):
        """(kind, count) for a runs/*.csv log - kind is "Variations Queue"
        for a rerun_prompts_comfyui.py-style log (its own "CSV File"
        column), "Generations" for a Generations-tab log (its own "File
        Path" column with no "Filename Prefix" - images already exist,
        nothing was queued to ComfyUI), or "Test Run" for a run_test.py/
        lora_test.py-style one. count is however many rows actually
        represent something real (skipped/error rows log an empty value
        and are naturally excluded)."""
        try:
            with open(log_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                rows = list(reader)
        except OSError:
            return "Unknown", 0

        if "CSV File" in fieldnames:
            return "Variations Queue", sum(1 for r in rows if r.get("Filename Prefix"))
        if "File Path" in fieldnames and "Filename Prefix" not in fieldnames:
            return "Generations", sum(1 for r in rows if r.get("File Path"))
        return "Test Run", sum(1 for r in rows if r.get("Filename Prefix"))

    def _resolve_run_images(self, log_path):
        """Snapshot of whatever image files currently exist on disk for a
        logged run. A Generations-tab log (see _write_generations_results_
        log) lists each row's own File Path directly - those images
        already exist, nothing was rendered. Everything else (run_test.py/
        lora_test.py/rerun_prompts_comfyui.py) globs "<prefix>_*" under
        ComfyUI's output folder instead (ComfyUI appends its own numeric
        counter and extension to filename_prefix) - no polling ComfyUI,
        just whatever's there right now, so a still-in-progress run simply
        shows fewer images than it'll end up with."""
        try:
            with open(log_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                rows = list(reader)
        except OSError:
            return []

        if "File Path" in fieldnames and "Filename Prefix" not in fieldnames:
            seen = set()
            images = []
            for row in rows:
                file_path = (row.get("File Path") or "").strip()
                if not file_path:
                    continue
                found = Path(file_path)
                if found.is_file() and found not in seen:
                    seen.add(found)
                    images.append(found)
            images.sort()
            return images

        comfyui_install_dir = self.settings.get("comfyui_install_dir")
        if not comfyui_install_dir:
            return []
        output_dir = Path(comfyui_install_dir) / "output"
        prefixes = [r["Filename Prefix"] for r in rows if r.get("Filename Prefix")]

        seen = set()
        images = []
        for prefix in prefixes:
            prefix_path = output_dir / prefix
            if not prefix_path.parent.is_dir():
                continue
            for found in prefix_path.parent.glob(prefix_path.name + "_*"):
                if found.is_file() and found not in seen:
                    seen.add(found)
                    images.append(found)
        images.sort()
        return images

    def _on_results_selection_changed(self, current, _previous):
        self.results_images_view.clear()
        self._results_gallery_anchor_row = None  # stale row indices once the gallery's rebuilt
        self._suppress_select_all_toggle = True
        self.select_all_images_check.setChecked(True)  # every image starts checked - see the per-item flag below
        self._suppress_select_all_toggle = False
        self.create_grid_button.setEnabled(current is not None)
        self.results_loading_label.setVisible(False)
        if current is None:
            return
        log_path = Path(current.data(Qt.UserRole))
        image_paths = self._resolve_run_images(log_path)
        if not image_paths:
            return

        icon_size = self.results_images_view.iconSize()
        blank_pixmap = QPixmap(icon_size)
        blank_pixmap.fill(Qt.transparent)
        blank_icon = QIcon(blank_pixmap)  # correctly-sized (not empty) placeholder - with
        # setUniformItemSizes(True), Qt caches the FIRST item's sizeHint and reuses it for
        # every item's on-screen bounding box, so an empty icon here would cap every real
        # thumbnail's rendered size to that of an empty icon once _on_thumbnail_ready sets it
        for path in image_paths:
            item = QListWidgetItem(blank_icon, "")  # real icon filled in as it loads, see _on_thumbnail_ready
            item.setData(Qt.UserRole, str(path))
            item.setData(Qt.UserRole + 1, True)  # checked by default - own overlay, not Qt's native checkbox
            item.setToolTip(path.name)
            self.results_images_view.addItem(item)

        self.results_loading_label.setVisible(True)
        loader = ThumbnailLoaderThread(image_paths, icon_size, self)
        self._thumbnail_loaders.append(loader)  # keep a live reference until it finishes - see thumbnail_loader_thread.py
        loader.thumbnail_ready.connect(self._on_thumbnail_ready)
        loader.finished_loading.connect(lambda loader=loader: self._on_thumbnails_finished(loader))
        loader.start()

    def _on_thumbnail_ready(self, index, path_str, image):
        """A previous selection's loader can still be delivering results
        after the gallery's been cleared and rebuilt for a new one - guard
        by checking the item at this index still points at the same path
        before touching it, rather than trying to cancel the old thread."""
        if index >= self.results_images_view.count():
            return
        item = self.results_images_view.item(index)
        if item.data(Qt.UserRole) != path_str or image.isNull():
            return
        checked = bool(item.data(Qt.UserRole + 1))
        item.setIcon(self._compose_thumbnail_icon(QPixmap.fromImage(image), self.results_images_view.iconSize(), checked=checked))

    def _on_thumbnails_finished(self, loader):
        if loader in self._thumbnail_loaders:
            self._thumbnail_loaders.remove(loader)
        if not self._thumbnail_loaders:
            self.results_loading_label.setVisible(False)

    def _make_thumbnail_icon(self, path, icon_size, checked):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        return self._compose_thumbnail_icon(pixmap, icon_size, checked)

    def _compose_thumbnail_icon(self, pixmap, icon_size, checked):
        """A thumbnail icon with a green checkmark badge composited onto its
        bottom-left corner when checked - Qt's native item checkbox always
        renders to the left of the icon and can't be repositioned without a
        custom item delegate, so this bakes the indicator into the icon
        pixmap itself instead."""
        scaled = pixmap.scaled(icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QPixmap(icon_size)
        canvas.fill(Qt.transparent)
        x = (icon_size.width() - scaled.width()) // 2
        y = (icon_size.height() - scaled.height()) // 2
        painter = QPainter(canvas)
        painter.drawPixmap(x, y, scaled)
        if checked:
            self._paint_check_badge(painter, x, y + scaled.height())
        painter.end()
        return QIcon(canvas)

    def _paint_check_badge(self, painter, image_left, image_bottom):
        diameter = 22
        cx = image_left + 3
        cy = image_bottom - diameter - 3
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(46, 160, 67))
        painter.setPen(QPen(Qt.white, 2))
        painter.drawEllipse(cx, cy, diameter, diameter)
        painter.drawLine(cx + 5, cy + 11, cx + 9, cy + 15)
        painter.drawLine(cx + 9, cy + 15, cx + 17, cy + 6)

    def _set_item_checked(self, item, checked):
        item.setData(Qt.UserRole + 1, checked)
        icon = self._make_thumbnail_icon(item.data(Qt.UserRole), self.results_images_view.iconSize(), checked)
        if icon is not None:
            item.setIcon(icon)

    def _on_results_image_clicked(self, item):
        clicked_row = self.results_images_view.row(item)
        if QApplication.keyboardModifiers() & Qt.ShiftModifier and self._results_gallery_anchor_row is not None:
            # Windows-Explorer-style range select: check every thumbnail
            # between the last plain click and this one, inclusive, in
            # either direction - doesn't touch anything outside that range,
            # and doesn't move the anchor (a further shift-click extends
            # from the same original anchor, not from this one).
            lo, hi = sorted((self._results_gallery_anchor_row, clicked_row))
            for i in range(lo, hi + 1):
                self._set_item_checked(self.results_images_view.item(i), True)
            return

        self._results_gallery_anchor_row = clicked_row
        self._set_item_checked(item, not item.data(Qt.UserRole + 1))

    def _on_select_all_images_toggled(self, _state):
        if getattr(self, "_suppress_select_all_toggle", False):
            return
        checked = self.select_all_images_check.isChecked()
        icon_size = self.results_images_view.iconSize()
        for i in range(self.results_images_view.count()):
            item = self.results_images_view.item(i)
            item.setData(Qt.UserRole + 1, checked)
            icon = self._make_thumbnail_icon(item.data(Qt.UserRole), icon_size, checked)
            if icon is not None:
                item.setIcon(icon)

    def _on_open_full_image(self, item):
        nav_paths = [Path(self.results_images_view.item(i).data(Qt.UserRole)) for i in range(self.results_images_view.count())]
        current_run = self.results_list.currentItem()
        log_path = Path(current_run.data(Qt.UserRole)) if current_run is not None else None
        self._show_full_image_dialog(
            item.data(Qt.UserRole), nav_paths=nav_paths, nav_index=self.results_images_view.row(item),
            log_path=log_path, default_save_dir=Path(item.data(Qt.UserRole)).parent,
        )

    def _prompt_text_for_image(self, log_path, image_path):
        """Best-effort prompt text for one output image. A Generations-tab
        log (its own "File Path" column, no "Filename Prefix") matches by
        exact File Path - one row per image - and shows Cleaned Prompt
        plus its Content Rating, since both are recorded right there.
        Otherwise, matched by Filename Prefix in the run's log: only
        available for a "Test Run" log (run_test.py/lora_test.py) whose
        sweep had more than one prompt - those are the only case that
        records a "Prompt" column at all; a single/default-prompt run has
        nothing to look up, and a "Variations Queue" log
        (rerun_prompts_comfyui.py) only records its *source* CSV's bare
        filename (no directory), too fragile to safely re-resolve back to
        prompt text. Returns None in every case with nothing to show."""
        if log_path is None:
            return None
        try:
            with open(log_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []

                if "File Path" in fieldnames and "Filename Prefix" not in fieldnames:
                    image_path_str = str(Path(image_path))
                    for row in reader:
                        if (row.get("File Path") or "").strip() != image_path_str:
                            continue
                        text = (row.get("Cleaned Prompt") or "").strip()
                        rating = (row.get("Content Rating") or "").strip()
                        if text and rating:
                            return f"{text} [{rating}]"
                        return text or None
                    return None

                if "Prompt" not in fieldnames:
                    return None
                image_stem = Path(image_path).stem
                for row in reader:
                    prefix = row.get("Filename Prefix")
                    if prefix and image_stem.startswith(Path(prefix).name + "_"):
                        return (row.get("Prompt") or "").strip() or None
        except OSError:
            return None
        return None

    def _show_full_image_dialog(self, path, default_save_dir=None, nav_paths=None, nav_index=None, log_path=None):
        """nav_paths/nav_index (used when opened from the Results gallery)
        add Previous/Next buttons that step through that same list of
        images in place, wrapping past either end back to the other -
        Next past the last image goes to the first, Previous before the
        first goes to the last. log_path (same source) shows that image's
        prompt text below it, when the run's log recorded one - see
        _prompt_text_for_image."""
        path = Path(path)
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return
        if not nav_paths:
            nav_paths = [path]
            nav_index = 0
        state = {"index": nav_index}

        dialog = QDialog(self)
        layout = QVBoxLayout(dialog)

        image_row = QHBoxLayout()
        prev_button = QPushButton("<")
        prev_button.setFixedWidth(32)
        image_label = QLabel()
        next_button = QPushButton(">")
        next_button.setFixedWidth(32)
        image_row.addWidget(prev_button)
        image_row.addWidget(image_label, 1)
        image_row.addWidget(next_button)
        layout.addLayout(image_row)

        screen_size = self.screen().availableSize() if self.screen() else QSize(1000, 800)
        max_size = QSize(int(screen_size.width() * 0.85), int(screen_size.height() * 0.85))

        prompt_label = QLabel()
        prompt_label.setWordWrap(True)
        prompt_label.setMaximumWidth(max_size.width())
        prompt_label.setVisible(log_path is not None)
        layout.addWidget(prompt_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        save_close_button = None
        if default_save_dir is not None:
            save_close_button = buttons.addButton("Save && Close", QDialogButtonBox.ActionRole)
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)

        def show_current():
            current_path = nav_paths[state["index"]]
            dialog.setWindowTitle(current_path.name)
            current_pixmap = QPixmap(str(current_path))
            if not current_pixmap.isNull():
                image_label.setPixmap(current_pixmap.scaled(max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if log_path is not None:
                prompt_text = self._prompt_text_for_image(log_path, current_path)
                prompt_label.setText(f"Prompt: {prompt_text}" if prompt_text else "Prompt: (not recorded for this run)")

        def navigate(delta):
            state["index"] = (state["index"] + delta) % len(nav_paths)
            show_current()

        show_nav = len(nav_paths) > 1
        prev_button.setVisible(show_nav)
        next_button.setVisible(show_nav)
        prev_button.clicked.connect(lambda: navigate(-1))
        next_button.clicked.connect(lambda: navigate(1))
        if save_close_button is not None:
            def save_and_close():
                if self._on_save_image_clicked(nav_paths[state["index"]], default_save_dir):
                    dialog.close()
            save_close_button.clicked.connect(save_and_close)

        show_current()
        dialog.exec()

    def _on_save_image_clicked(self, path, default_save_dir):
        """Returns True once the image is actually saved, False if the save
        dialog was cancelled or the copy itself failed - the modal's Save &
        Close button only closes on True, so a cancel or a failure leaves it
        open instead of losing your place."""
        default_path = Path(default_save_dir) / path.name
        chosen_path, _ = QFileDialog.getSaveFileName(
            self, "Save image", str(default_path), "PNG files (*.png)"
        )
        if not chosen_path:
            return False
        try:
            shutil.copyfile(path, chosen_path)
        except OSError as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return False
        self._log(f"Saved {path.name} to {chosen_path}")
        return True

    def _checked_result_images(self):
        return [
            Path(self.results_images_view.item(i).data(Qt.UserRole))
            for i in range(self.results_images_view.count())
            if self.results_images_view.item(i).data(Qt.UserRole + 1)
        ]

    def _on_create_grid_clicked(self):
        item = self.results_list.currentItem()
        if item is None:
            return
        comfyui_install_dir = self.settings.get("comfyui_install_dir")
        if not comfyui_install_dir:
            QMessageBox.warning(self, "ComfyUI folder not set", "Set your ComfyUI installation folder in Settings first.")
            return

        selected_images = self._checked_result_images()
        self._log(f"Create Grid: {len(selected_images)} image(s) checked in the gallery.")
        if len(selected_images) < 2:
            QMessageBox.warning(
                self, "Not enough images selected",
                "Check at least 2 images in the gallery on the right to create a grid from them.",
            )
            return

        log_path = Path(item.data(Qt.UserRole))
        output_dir = Path(comfyui_install_dir) / "output"
        grid_path = RUNS_DIR / "grids" / f"{log_path.stem}_grid.png"

        try:
            grid_paths = comparison_grid.build_comparison_grid(log_path, output_dir, grid_path, selected_images=selected_images)
        except ValueError as e:
            QMessageBox.warning(self, "Can't create grid", str(e))
            return
        except OSError as e:
            QMessageBox.critical(self, "Grid creation failed", str(e))
            return

        self._log(f"Comparison grid(s) saved: {', '.join(str(p) for p in grid_paths)}")
        images_dir = selected_images[0].parent
        for path in grid_paths:
            self._show_full_image_dialog(path, default_save_dir=images_dir)

    def _on_delete_selected_result(self):
        log_paths = self._checked_results_runs()
        if not log_paths:
            return
        images_by_run = {
            log_path: self._resolve_run_images(log_path) if self.settings.get("comfyui_install_dir") else []
            for log_path in log_paths
        }
        total_images = sum(len(images) for images in images_by_run.values())

        if len(log_paths) == 1:
            message = f"Delete this run's log ({log_paths[0].name})"
            if total_images:
                message += f" and its {total_images} output image(s)"
        else:
            message = f"Delete these {len(log_paths)} runs' logs"
            if total_images:
                message += f" and their {total_images} output image(s) total"
        message += "?\n\nThis cannot be undone."
        if QMessageBox.question(self, "Delete run(s)", message) != QMessageBox.Yes:
            return

        for log_path, images in images_by_run.items():
            for image_path in images:
                try:
                    image_path.unlink()
                except OSError as e:
                    self._log(f"Warning: could not delete {image_path}: {e}")
            try:
                log_path.unlink()
            except OSError as e:
                self._log(f"Warning: could not delete {log_path}: {e}")

    # ---- Generations tab: extract/clean/rate a directory of images ------------

    def _build_generations_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(
            "Scans a directory of images (comfy_prompt_tools.extract_and_clean), "
            "reads each one's embedded generation metadata, rewrites the prompt "
            "for a modern text-to-image model, and content-rates it - all via a "
            "local Ollama model. An image with no metadata at all is described "
            "directly instead of being skipped."
        ))

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Ollama model:"))
        self.generations_model_combo = QComboBox()
        self.generations_model_combo.setEditable(True)  # in case Ollama's unreachable or the wanted model isn't pulled yet
        self._populate_generations_model_dropdown()
        options_row.addWidget(self.generations_model_combo, 1)
        options_row.addWidget(QLabel("Prompt style:"))
        self.generations_prompt_config_combo = QComboBox()
        self.generations_prompt_config_combo.setToolTip(
            "Which prompt-directions file to build the cleaning instructions from - different models can respond "
            "very differently to the same wording, so each one can have its own file "
            "(comfy_prompt_tools/clean_prompts*.json) instead of sharing one."
        )
        self._populate_generations_prompt_config_dropdown()
        options_row.addWidget(self.generations_prompt_config_combo)
        self.generations_overwrite_check = QCheckBox("Overwrite")
        self.generations_overwrite_check.setToolTip(
            "Reprocess rows that already have a Cleaned Prompt (default: skip them)."
        )
        options_row.addWidget(self.generations_overwrite_check)
        edit_cleaning_prompt_button = QPushButton("Edit Cleaning Prompt...")
        edit_cleaning_prompt_button.setToolTip(
            "View/edit the instructions sent to Ollama for rewriting each prompt "
            "(comfy_prompt_tools.clean_prompts.SYSTEM_PROMPT) - not a prompt itself, "
            "the direction the model follows to clean one."
        )
        edit_cleaning_prompt_button.clicked.connect(self._edit_cleaning_prompt)
        options_row.addWidget(edit_cleaning_prompt_button)
        left_layout.addLayout(options_row)
        # Shared by both sections below - Ollama model / Overwrite apply to
        # whichever button is actually clicked.

        directory_group = QGroupBox("Directory")
        directory_layout = QVBoxLayout(directory_group)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Directory:"))
        self.generations_dir_edit = QLineEdit()
        dir_row.addWidget(self.generations_dir_edit, 1)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse_generations_dir)
        dir_row.addWidget(browse_button)
        directory_layout.addLayout(dir_row)

        buttons_row = QHBoxLayout()
        self.generations_extract_button = QPushButton("Extract")
        self.generations_extract_button.setToolTip(
            "Just reads embedded generation metadata into a CSV - no Ollama, no ComfyUI."
        )
        self.generations_extract_button.clicked.connect(self._on_generations_extract_clicked)
        buttons_row.addWidget(self.generations_extract_button)
        self.generations_clean_button = QPushButton("Extract + Clean + Rate")
        self.generations_clean_button.setToolTip(
            "Extracts, then rewrites and content-rates each prompt via Ollama (comfy_prompt_tools.extract_and_clean)."
        )
        self.generations_clean_button.clicked.connect(self._on_generations_extract_clean_rate_clicked)
        buttons_row.addWidget(self.generations_clean_button)
        self.generations_queue_button = QPushButton("Extract + Clean + Rate + Queue")
        self.generations_queue_button.setToolTip(
            "Same as Extract + Clean + Rate, then submits each cleaned prompt to ComfyUI "
            "using the workflow selected on the Testing tab."
        )
        self.generations_queue_button.clicked.connect(self._on_generations_extract_clean_rate_queue_clicked)
        buttons_row.addWidget(self.generations_queue_button)
        directory_layout.addLayout(buttons_row)

        left_layout.addWidget(directory_group)

        csv_group = QGroupBox("Clean Existing CSV(s)")
        csv_group.setToolTip("Skips extraction - cleans/rates whatever's already in the chosen CSV(s).")
        csv_group_layout = QVBoxLayout(csv_group)

        csv_row = QHBoxLayout()
        self.generations_csv_list = QListWidget()
        self.generations_csv_list.setFixedHeight(90)  # QListWidget defaults to an expanding vertical size policy - setMaximumHeight alone doesn't stop it claiming leftover layout space
        csv_row.addWidget(self.generations_csv_list, 1)
        csv_buttons_col = QVBoxLayout()
        csv_browse_button = QPushButton("Browse...")
        csv_browse_button.clicked.connect(self._on_browse_generations_csvs)
        csv_buttons_col.addWidget(csv_browse_button)
        csv_clear_button = QPushButton("Clear")
        csv_clear_button.clicked.connect(self._on_clear_generations_csvs)
        csv_buttons_col.addWidget(csv_clear_button)
        csv_prompts_button = QPushButton("Prompts...")
        csv_prompts_button.setToolTip(
            "View/edit the raw Positive Prompt text across every loaded CSV before cleaning - "
            "never shows Cleaned Prompt. Saving overrides the source CSV file(s)."
        )
        csv_prompts_button.clicked.connect(self._on_generations_edit_csv_prompts)
        csv_buttons_col.addWidget(csv_prompts_button)
        csv_row.addLayout(csv_buttons_col)
        csv_group_layout.addLayout(csv_row)

        csv_actions_row = QHBoxLayout()
        self.generations_clean_csv_button = QPushButton("Clean Selected CSV(s)")
        self.generations_clean_csv_button.setToolTip(
            "Rewrites and content-rates each selected CSV's prompts via Ollama - no extraction, no ComfyUI."
        )
        self.generations_clean_csv_button.clicked.connect(self._on_generations_clean_csvs_clicked)
        csv_actions_row.addWidget(self.generations_clean_csv_button)
        self.generations_clean_queue_csv_button = QPushButton("Clean + Queue Selected CSV(s)")
        self.generations_clean_queue_csv_button.setToolTip(
            "Same as Clean, then submits each cleaned prompt to ComfyUI using the workflow selected on the Testing tab."
        )
        self.generations_clean_queue_csv_button.clicked.connect(self._on_generations_clean_queue_csvs_clicked)
        csv_actions_row.addWidget(self.generations_clean_queue_csv_button)
        csv_group_layout.addLayout(csv_actions_row)

        left_layout.addWidget(csv_group)

        self.generations_log_view = QPlainTextEdit()
        self.generations_log_view.setReadOnly(True)
        self.generations_log_view.setMaximumBlockCount(5000)
        self._add_collapsible_log(page, left_layout, self.generations_log_view)

        # Keeps the two group boxes (and the collapsed log toggle) packed at
        # the top instead of spread out to fill the splitter pane's full
        # height. The log itself already has stretch factor 1 from
        # _add_collapsible_log - heavily outweighting this trailing spacer's
        # own share (100:1) means the log still claims nearly all leftover
        # space once expanded, while this spacer is what keeps things tight
        # while it's collapsed.
        left_layout.addStretch(1)
        left_layout.setStretchFactor(self.generations_log_view, 100)

        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.generations_loading_label = QLabel("Loading images...")
        self.generations_loading_label.setVisible(False)
        right_layout.addWidget(self.generations_loading_label)

        generations_icon_size = QSize(440, 440)
        self.generations_images_view = QListWidget()
        self.generations_images_view.setViewMode(QListWidget.IconMode)
        self.generations_images_view.setIconSize(generations_icon_size)
        self.generations_images_view.setGridSize(
            QSize(generations_icon_size.width() + 1, generations_icon_size.height() + 5)
        )
        self.generations_images_view.setResizeMode(QListWidget.Adjust)
        self.generations_images_view.setMovement(QListWidget.Static)
        self.generations_images_view.setUniformItemSizes(True)
        self.generations_images_view.itemDoubleClicked.connect(self._on_generations_image_double_clicked)
        right_layout.addWidget(self.generations_images_view, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([450, 900])
        layout.addWidget(splitter, 1)

        self.generations_dir_edit.textChanged.connect(lambda _text: self._refresh_generations_gallery())

        return page

    def _on_browse_generations_dir(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose directory to scan", self.generations_dir_edit.text() or self._csv_browse_default_dir()
        )
        if chosen:
            self.generations_dir_edit.setText(chosen)

    def _populate_generations_model_dropdown(self):
        """Same idea as _populate_ollama_model_dropdown (Variations tab), but
        defaulting to clean_prompts.MODEL instead of generate_prompt_
        variations.DEFAULT_MODEL - each script has its own default model."""
        models = generate_prompt_variations.list_ollama_models()
        if CLEAN_PROMPTS_DEFAULT_MODEL not in models:
            models = [CLEAN_PROMPTS_DEFAULT_MODEL] + models
        self.generations_model_combo.addItems(models)
        self.generations_model_combo.setCurrentText(CLEAN_PROMPTS_DEFAULT_MODEL)

    def _populate_generations_prompt_config_dropdown(self):
        """Discovers every clean_prompts*.json prompt-directions file next to
        clean_prompts.py itself (clean_prompts.json plus any per-model ones
        like clean_prompts_qwen.json), skipping the gitignored *.local.json
        override files - those get merged in automatically by clean_prompts.
        build_system_prompt(), never picked directly. clean_prompts.json
        itself is always listed first, labeled "Default", regardless of
        glob order."""
        config_dir = clean_prompts.SYSTEM_PROMPT_CONFIG_PATH.parent
        paths = sorted(
            p for p in config_dir.glob("clean_prompts*.json") if not p.name.endswith(".local.json")
        )
        default_path = clean_prompts.SYSTEM_PROMPT_CONFIG_PATH
        paths.sort(key=lambda p: p != default_path)  # default_path first, others alphabetical after

        self.generations_prompt_config_combo.clear()
        for path in paths:
            if path == default_path:
                label = "Default"
            else:
                # clean_prompts_qwen.json -> "Qwen"
                stem = path.stem
                suffix = stem[len("clean_prompts"):].lstrip("_") or stem
                label = suffix.replace("_", " ").title()
            self.generations_prompt_config_combo.addItem(label, str(path))

    def _selected_generations_prompt_config(self):
        """Path (as str) of the prompt-directions file currently chosen in
        the Prompt style dropdown, or None for the default clean_prompts.json
        - clean_prompts.run()/clean_all() already fall back to that default
        when prompt_config is omitted, so the written config just skips the
        key entirely in that case rather than special-casing "Default" here
        too."""
        path = self.generations_prompt_config_combo.currentData()
        return path if path and path != str(clean_prompts.SYSTEM_PROMPT_CONFIG_PATH) else None

    def _edit_cleaning_prompt(self):
        """View/edit clean_prompts.py's text-rewrite system prompt - the
        base instructions (clean_prompts.json, checked in) and the
        optional personal addendum (clean_prompts.local.json, gitignored)
        that gets appended to it, same base+local split as everywhere
        else in comfy-prompt-tools. This is the *cleaning* instructions,
        not a prompt to be cleaned - the content-rating rubric appended
        on top of this at request time (see clean_prompts._combined_
        system_prompt) isn't shown here, since that's rate_prompts.py's
        own file to edit, not this one's."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Cleaning Prompt")
        dialog.setMinimumSize(640, 560)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "Instructions comfy_prompt_tools.clean_prompts.py sends to Ollama for "
            "rewriting each prompt - not a prompt itself, the direction the model "
            "follows to clean one. Base is checked into the repo; Local is your own "
            "optional personal addition, appended after it and never committed."
        ))

        base_text = clean_prompts.load_text(clean_prompts.SYSTEM_PROMPT_CONFIG_PATH, "system_prompt_base")
        local_text = clean_prompts.load_local_text(clean_prompts.SYSTEM_PROMPT_CONFIG_PATH, "system_prompt_addendum")

        layout.addWidget(QLabel("Base (clean_prompts.json):"))
        base_edit = QPlainTextEdit(base_text)
        layout.addWidget(base_edit, 2)

        layout.addWidget(QLabel("Local addendum (clean_prompts.local.json) - optional, appended after Base:"))
        local_edit = QPlainTextEdit(local_text)
        layout.addWidget(local_edit, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        base_path = clean_prompts.SYSTEM_PROMPT_CONFIG_PATH
        base_config = json.loads(base_path.read_text(encoding="utf-8"))
        base_config["system_prompt_base"] = base_edit.toPlainText()
        base_path.write_text(json.dumps(base_config, indent=2), encoding="utf-8")

        local_path = local_path_for(base_path)
        local_config = json.loads(local_path.read_text(encoding="utf-8")) if local_path.is_file() else {}
        local_config["system_prompt_addendum"] = local_edit.toPlainText()
        local_path.write_text(json.dumps(local_config, indent=2), encoding="utf-8")

        # Take effect immediately in this running session, same as Edit LoRA Rules...
        clean_prompts.SYSTEM_PROMPT = clean_prompts._combined_system_prompt(clean_prompts.build_system_prompt())
        self.generations_log_view.appendPlainText(f"Saved cleaning prompt to {base_path.name} / {local_path.name}")

    def _resolve_generations_images(self, directory):
        root = Path(directory)
        if not root.is_dir():
            return []
        return sorted(
            p for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in extract_image_prompts.IMAGE_EXTENSIONS
        )

    def _images_from_csvs(self, csv_paths):
        """Every distinct, still-existing image referenced by these CSVs'
        own File Path column - used to preview what a Clean CSV(s) action
        is about to touch, same idea as _resolve_generations_images for a
        directory scan."""
        seen = set()
        images = []
        for csv_path in csv_paths:
            try:
                with open(csv_path, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        file_path = (row.get("File Path") or "").strip()
                        if not file_path:
                            continue
                        found = Path(file_path)
                        if found.is_file() and found not in seen:
                            seen.add(found)
                            images.append(found)
            except OSError:
                continue
        images.sort()
        return images

    def _refresh_generations_gallery(self):
        directory = self.generations_dir_edit.text().strip()
        image_paths = self._resolve_generations_images(directory) if directory else []
        self._populate_generations_gallery(image_paths)

    def _populate_generations_gallery(self, image_paths):
        self.generations_images_view.clear()
        self.generations_loading_label.setVisible(False)
        if not image_paths:
            return

        icon_size = self.generations_images_view.iconSize()
        blank_pixmap = QPixmap(icon_size)
        blank_pixmap.fill(Qt.transparent)
        blank_icon = QIcon(blank_pixmap)  # see thumbnail_loader_thread.py / Results tab for why not an empty icon
        for path in image_paths:
            item = QListWidgetItem(blank_icon, "")
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(path.name)
            self.generations_images_view.addItem(item)

        self.generations_loading_label.setVisible(True)
        loader = ThumbnailLoaderThread(image_paths, icon_size, self)
        self._generations_thumbnail_loaders.append(loader)
        loader.thumbnail_ready.connect(self._on_generations_thumbnail_ready)
        loader.finished_loading.connect(lambda loader=loader: self._on_generations_thumbnails_finished(loader))
        loader.start()

    def _on_generations_thumbnail_ready(self, index, path_str, image):
        if index >= self.generations_images_view.count():
            return
        item = self.generations_images_view.item(index)
        if item.data(Qt.UserRole) != path_str or image.isNull():
            return
        item.setIcon(self._compose_thumbnail_icon(QPixmap.fromImage(image), self.generations_images_view.iconSize(), checked=False))

    def _on_generations_thumbnails_finished(self, loader):
        if loader in self._generations_thumbnail_loaders:
            self._generations_thumbnail_loaders.remove(loader)
        if not self._generations_thumbnail_loaders:
            self.generations_loading_label.setVisible(False)

    def _on_generations_image_double_clicked(self, item):
        nav_paths = [
            Path(self.generations_images_view.item(i).data(Qt.UserRole))
            for i in range(self.generations_images_view.count())
        ]
        self._show_full_image_dialog(
            item.data(Qt.UserRole), nav_paths=nav_paths, nav_index=self.generations_images_view.row(item)
        )

    def _generations_directory_or_warn(self):
        directory = self.generations_dir_edit.text().strip()
        if not directory or not Path(directory).is_dir():
            QMessageBox.warning(self, "No directory", "Choose a valid directory to scan first.")
            return None
        return directory

    def _set_generations_buttons_enabled(self, enabled):
        self.generations_extract_button.setEnabled(enabled)
        self.generations_clean_button.setEnabled(enabled)
        self.generations_queue_button.setEnabled(enabled)
        self.generations_clean_csv_button.setEnabled(enabled)
        self.generations_clean_queue_csv_button.setEnabled(enabled)

    def _start_generations_thread(self, run_func, arg, results_source):
        """results_source is ("directory", directory) or ("csvs", csv_paths)
        - which one determines how _on_generations_finished_ok resolves the
        gallery refresh and the Results-tab log afterward."""
        self._generations_pending_results_source = results_source
        self._set_generations_buttons_enabled(False)
        self.generations_log_view.clear()
        self._generations_thread = TestRunnerThread(run_func, arg, self)
        self._generations_thread.log_line.connect(self.generations_log_view.appendPlainText)
        self._generations_thread.finished_ok.connect(self._on_generations_finished_ok)
        self._generations_thread.finished_error.connect(self._on_generations_finished_error)
        self._generations_thread.start()

    def _on_generations_extract_clicked(self):
        """Metadata extraction only - extract_image_prompts.extract_all()
        takes the directory directly, so no JSON config file is needed at
        all for this one (unlike the other two buttons)."""
        directory = self._generations_directory_or_warn()
        if directory is None:
            return
        self._start_generations_thread(extract_image_prompts.extract_all, directory, ("directory", directory))

    def _on_generations_extract_clean_rate_clicked(self):
        directory = self._generations_directory_or_warn()
        if directory is None:
            return
        config = {
            "directory": directory,
            "model": self.generations_model_combo.currentText().strip() or CLEAN_PROMPTS_DEFAULT_MODEL,
            "overwrite": self.generations_overwrite_check.isChecked(),
            "verbose": True,  # keep File Path etc. - the Results tab log needs it, see _write_generations_results_log_from_csvs
        }
        prompt_config = self._selected_generations_prompt_config()
        if prompt_config:
            config["prompt_config"] = prompt_config
        GUI_GENERATIONS_RUN_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._start_generations_thread(extract_and_clean.run, GUI_GENERATIONS_RUN_CONFIG_PATH, ("directory", directory))

    def _on_generations_extract_clean_rate_queue_clicked(self):
        directory = self._generations_directory_or_warn()
        if directory is None:
            return

        workflow_path = self._generations_selected_workflow_or_warn()
        if workflow_path is None:
            return

        config = {
            "directory": directory,
            "model": self.generations_model_combo.currentText().strip() or CLEAN_PROMPTS_DEFAULT_MODEL,
            "overwrite": self.generations_overwrite_check.isChecked(),
            "verbose": True,  # keep File Path etc. - the Results tab log needs it, see _write_generations_results_log_from_csvs
            "submit_to_comfyui": True,
            "workflow": str(workflow_path),
            "server": self.settings["server"],
        }
        prompt_config = self._selected_generations_prompt_config()
        if prompt_config:
            config["prompt_config"] = prompt_config
        if not self._confirm_json(
            "Confirm queue job", config,
            "About to extract, clean, rate, and queue this directory's images to ComfyUI:", "Queue",
        ):
            return
        GUI_GENERATIONS_RUN_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._start_generations_thread(extract_and_clean.run, GUI_GENERATIONS_RUN_CONFIG_PATH, ("directory", directory))

    def _generations_selected_workflow_or_warn(self):
        """Resolves the Testing tab's currently-selected workflow to a
        local file path, same validation as Queue Generated Variations -
        shared by both the directory Queue button and the CSV Clean+Queue
        button below."""
        workflow_name = self.workflow_combo.currentText().strip()
        if not workflow_name:
            QMessageBox.warning(self, "No workflow selected", "Pick a source workflow on the Testing tab first.")
            return None
        comfyui_install_dir = self.settings.get("comfyui_install_dir")
        if not comfyui_install_dir:
            QMessageBox.warning(self, "ComfyUI folder not set", "Set your ComfyUI installation folder in Settings first.")
            return None
        workflow_path = Path(comfyui_install_dir) / "user" / "default" / "workflows" / workflow_name
        if not workflow_path.is_file():
            QMessageBox.warning(self, "Workflow not found", f"File not found:\n{workflow_path}")
            return None
        return workflow_path

    def _generations_selected_csv_paths(self):
        return [self.generations_csv_list.item(i).text() for i in range(self.generations_csv_list.count())]

    def _on_browse_generations_csvs(self):
        """Adds to the current selection rather than replacing it, so
        picking CSVs across more than one Browse click accumulates
        instead of the later pick wiping out the earlier one."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choose CSV file(s) to clean", self._csv_browse_default_dir(), "CSV files (*.csv)"
        )
        if not paths:
            return
        existing = set(self._generations_selected_csv_paths())
        for path in paths:
            if path not in existing:
                self.generations_csv_list.addItem(path)
                existing.add(path)
        self._populate_generations_gallery(self._images_from_csvs(self._generations_selected_csv_paths()))

    def _on_clear_generations_csvs(self):
        self.generations_csv_list.clear()
        self._populate_generations_gallery([])

    def _generations_csv_paths_or_warn(self):
        csv_paths = self._generations_selected_csv_paths()
        if not csv_paths:
            QMessageBox.warning(self, "No CSVs selected", "Choose one or more CSV files to clean first.")
            return None
        return csv_paths

    def _generations_raw_prompts_from_csvs(self, csv_paths):
        """[(csv_path, row_index, positive_prompt_text), ...] for every row
        across these CSVs with non-empty Positive Prompt text - row_index
        is 0-based into that CSV's data rows (header excluded), used to
        write edits/removals back to the correct row on Save. Never looks
        at Cleaned Prompt - this previews/edits what clean_prompts.py is
        about to read, not what it may have already produced."""
        prompts = []
        for csv_path in csv_paths:
            try:
                with open(csv_path, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for i, row in enumerate(reader):
                        text = (row.get("Positive Prompt") or "").strip()
                        if text:
                            prompts.append((csv_path, i, text))
            except OSError:
                continue
        return prompts

    def _on_generations_edit_csv_prompts(self):
        csv_paths = self._generations_csv_paths_or_warn()
        if csv_paths is None:
            return
        prompts = self._generations_raw_prompts_from_csvs(csv_paths)
        if not prompts:
            QMessageBox.information(
                self, "No prompts found", "None of the selected CSV(s) have a non-empty Positive Prompt column."
            )
            return

        dialog = GenerationsCsvPromptsDialog(prompts, self)
        if dialog.exec() != QDialog.Accepted:
            return

        edits, removals = dialog.edits_and_removals(prompts)
        if not edits and not removals:
            return  # nothing actually changed

        changed_files = {path for path, _row in edits} | set(removals.keys())
        removed_count = sum(len(rows) for rows in removals.values())
        message = f"About to permanently modify {len(changed_files)} CSV file(s):\n"
        if edits:
            message += f"- {len(edits)} row(s) with edited Positive Prompt text\n"
        if removals:
            message += f"- {removed_count} row(s) removed entirely\n"
        message += "\nThis cannot be undone. Continue?"
        if QMessageBox.question(self, "Override CSV file(s)", message) != QMessageBox.Yes:
            return

        self._apply_generations_csv_prompt_changes(csv_paths, edits, removals)
        self.generations_log_view.appendPlainText(
            f"Prompts: updated {len(edits)} row(s), removed {removed_count} row(s) across {len(changed_files)} CSV file(s)."
        )
        self._populate_generations_gallery(self._images_from_csvs(self._generations_selected_csv_paths()))

    def _apply_generations_csv_prompt_changes(self, csv_paths, edits, removals):
        """Rewrites each affected CSV in place: an edited row gets its
        Positive Prompt column replaced; a removed row is dropped
        entirely. A CSV with neither is left completely untouched."""
        for csv_path in csv_paths:
            removed_indices = removals.get(csv_path, set())
            path_edits = {row_index: text for (path, row_index), text in edits.items() if path == csv_path}
            if not removed_indices and not path_edits:
                continue

            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)

            new_rows = []
            for i, row in enumerate(rows):
                if i in removed_indices:
                    continue
                if i in path_edits:
                    row["Positive Prompt"] = path_edits[i]
                new_rows.append(row)

            tmp_path = csv_path + ".tmp"
            with open(tmp_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(new_rows)
            os.replace(tmp_path, csv_path)

    def _on_generations_clean_csvs_clicked(self):
        csv_paths = self._generations_csv_paths_or_warn()
        if csv_paths is None:
            return
        config = {
            "csv_paths": csv_paths,
            "model": self.generations_model_combo.currentText().strip() or CLEAN_PROMPTS_DEFAULT_MODEL,
            "overwrite": self.generations_overwrite_check.isChecked(),
            "verbose": True,  # keep File Path etc. - the Results tab log needs it, see _write_generations_results_log_from_csvs
        }
        prompt_config = self._selected_generations_prompt_config()
        if prompt_config:
            config["prompt_config"] = prompt_config
        GUI_GENERATIONS_CLEAN_CSV_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._start_generations_thread(clean_prompts.run, GUI_GENERATIONS_CLEAN_CSV_CONFIG_PATH, ("csvs", csv_paths))

    def _on_generations_clean_queue_csvs_clicked(self):
        csv_paths = self._generations_csv_paths_or_warn()
        if csv_paths is None:
            return
        workflow_path = self._generations_selected_workflow_or_warn()
        if workflow_path is None:
            return

        config = {
            "csv_paths": csv_paths,
            "model": self.generations_model_combo.currentText().strip() or CLEAN_PROMPTS_DEFAULT_MODEL,
            "overwrite": self.generations_overwrite_check.isChecked(),
            "verbose": True,  # keep File Path etc. - the Results tab log needs it, see _write_generations_results_log_from_csvs
            "submit_to_comfyui": True,
            "workflow": str(workflow_path),
            "server": self.settings["server"],
        }
        prompt_config = self._selected_generations_prompt_config()
        if prompt_config:
            config["prompt_config"] = prompt_config
        if not self._confirm_json(
            "Confirm queue job", config, "About to clean and queue these CSV(s) to ComfyUI:", "Queue",
        ):
            return
        GUI_GENERATIONS_CLEAN_CSV_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._start_generations_thread(clean_prompts.run, GUI_GENERATIONS_CLEAN_CSV_CONFIG_PATH, ("csvs", csv_paths))

    def _on_generations_finished_ok(self):
        self._set_generations_buttons_enabled(True)
        self.generations_log_view.appendPlainText("Done.")
        source_kind, source_value = self._generations_pending_results_source
        if source_kind == "directory":
            self._refresh_generations_gallery()
            self._write_generations_results_log_from_directory(source_value)
        else:
            self._populate_generations_gallery(self._images_from_csvs(source_value))
            self._write_generations_results_log_from_csvs(source_value, log_name="cleaned_csvs")

    def _on_generations_finished_error(self, message):
        self._set_generations_buttons_enabled(True)
        self.generations_log_view.appendPlainText(f"Failed: {message}")
        QMessageBox.critical(self, "Generations failed", message)

    def _write_generations_results_log_from_directory(self, directory):
        if not directory:
            return
        csv_paths = sorted(Path(directory).rglob("*-prompts.csv"))
        if not csv_paths:
            return
        self._write_generations_results_log_from_csvs(csv_paths, log_name=Path(directory).name or "generations")

    def _write_generations_results_log_from_csvs(self, csv_paths, log_name="generations"):
        """After a Generations run finishes, writes a log into
        funkytown-testing-harness's runs/ folder (same folder run_test.py/
        lora_test.py/rerun_prompts_comfyui.py write to) so it shows up in
        the Results tab too, browsable the same way. Unlike those, this
        pipeline never renders anything - the images already exist - so
        each row's own File Path is recorded directly instead of a
        Filename Prefix to glob for a future render."""
        if not csv_paths:
            return

        fieldnames = ["File Name", "File Path", "Positive Prompt", "Cleaned Prompt", "Content Rating", "Rating Reason"]
        rows_out = []
        seen_paths = set()
        for csv_path in csv_paths:
            try:
                with open(csv_path, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        file_path = (row.get("File Path") or "").strip()
                        if not file_path or file_path in seen_paths or not Path(file_path).is_file():
                            continue
                        seen_paths.add(file_path)
                        rows_out.append({field: row.get(field, "") for field in fieldnames})
            except OSError:
                continue

        if not rows_out:
            return

        RUNS_DIR.mkdir(exist_ok=True)
        log_path = RUNS_DIR / f"{log_name}_{datetime.datetime.now():%y%m%d_%H%M%S}.csv"
        with open(log_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_out)

        self._refresh_results_list()
