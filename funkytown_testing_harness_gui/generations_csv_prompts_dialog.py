"""Popup for viewing/editing the Generations tab's raw prompts, aggregated
across every currently-loaded CSV - each row shows its source "Positive
Prompt" text (never "Cleaned Prompt", even if one's already there - the
point is reviewing/editing what clean_prompts.py is about to read, not
what it may have already produced) in an editable field, plus a delete
button to exclude that row from cleaning entirely. Unlike the Testing/
Variations tabs' prompt popups, Save here actually writes changes back to
the source CSV file(s) - overriding the Positive Prompt column for edited
rows, or removing the row entirely for deleted ones - since clean_prompts.py
itself only ever reads from real files on disk, not an in-memory override
list.
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class _CsvPromptRowWidget(QWidget):
    def __init__(self, csv_path, row_index, original_text, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self.row_index = row_index  # 0-based index into that CSV's data rows (header excluded)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        source_label = QLabel(Path(csv_path).name)
        source_label.setFixedWidth(160)
        source_label.setToolTip(csv_path)
        layout.addWidget(source_label)
        self.text_edit = QPlainTextEdit(original_text)
        self.text_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.text_edit.setFixedHeight(70)  # ~3 lines - long prompts scroll within the row instead of growing it
        layout.addWidget(self.text_edit, 1)
        self.remove_button = QToolButton()
        self.remove_button.setText("✕")
        self.remove_button.setAutoRaise(True)
        self.remove_button.setToolTip("Remove this row from its source CSV - takes effect on Save")
        layout.addWidget(self.remove_button)


class GenerationsCsvPromptsDialog(QDialog):
    def __init__(self, prompts, parent=None):
        """prompts: list of (csv_path, row_index, positive_prompt_text)
        tuples, in file-then-row order."""
        super().__init__(parent)
        self.setWindowTitle("Prompts")
        self.resize(680, 480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Raw Positive Prompt text clean_prompts.py is about to read from "
            "each loaded CSV (not Cleaned Prompt, even if one's already "
            "there) - edit a row's text or click ✕ to remove it "
            "entirely. Save writes these changes back to the source CSV "
            "file(s) - this cannot be undone."
        ))

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        for csv_path, row_index, text in prompts:
            self._add_row(csv_path, row_index, text)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Save (overrides CSV files)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_row(self, csv_path, row_index, text):
        item = QListWidgetItem()
        row_widget = _CsvPromptRowWidget(csv_path, row_index, text)
        item.setSizeHint(row_widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, row_widget)
        row_widget.remove_button.clicked.connect(lambda: self._remove_row(item))

    def _remove_row(self, item):
        self.list_widget.takeItem(self.list_widget.row(item))

    def edits_and_removals(self, original_prompts):
        """Compares the dialog's current state against the (csv_path,
        row_index, text) list it was built from, returning (edits,
        removals):
        - edits: {(csv_path, row_index): new_text} for rows whose text
          changed and are still present.
        - removals: {csv_path: {row_index, ...}} for rows deleted
          entirely (✕ clicked).
        """
        remaining = {}
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            remaining[(widget.csv_path, widget.row_index)] = widget.text_edit.toPlainText()

        edits = {}
        removals = {}
        for csv_path, row_index, original_text in original_prompts:
            key = (csv_path, row_index)
            if key not in remaining:
                removals.setdefault(csv_path, set()).add(row_index)
            elif remaining[key] != original_text:
                edits[key] = remaining[key]

        return edits, removals
