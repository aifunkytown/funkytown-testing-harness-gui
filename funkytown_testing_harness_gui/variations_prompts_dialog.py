"""Popup for viewing/editing the Variations tab's CSV-row-backed prompt
list - each row shows its source text in an editable field (overriding
that row's prompt) plus a delete button (skips that row entirely). Unlike
the Testing tab's Prompts popup, there's no "add new prompt" box here -
every row is tied to a specific CSV row for its other metadata (File Name,
Negative Prompt, etc.), so new unattached rows can't be added."""

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


class _PromptRowWidget(QWidget):
    def __init__(self, row_num, text, parent=None):
        super().__init__(parent)
        self.row_num = row_num
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        row_label = QLabel(f"Row {row_num}")
        row_label.setFixedWidth(55)
        layout.addWidget(row_label)
        self.text_edit = QPlainTextEdit(text)
        self.text_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.text_edit.setFixedHeight(70)  # ~3 lines - long prompts scroll within the row instead of growing it
        layout.addWidget(self.text_edit, 1)
        self.remove_button = QToolButton()
        self.remove_button.setText("✕")
        self.remove_button.setAutoRaise(True)
        self.remove_button.setToolTip("Skip this row - never touches the source CSV file")
        layout.addWidget(self.remove_button)


class VariationsPromptsDialog(QDialog):
    def __init__(self, prompts, parent=None):
        """prompts: list of (row_num, text) tuples, in row order."""
        super().__init__(parent)
        self.setWindowTitle("Prompts")
        self.resize(560, 460)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Each row's source text (Cleaned Prompt if present, otherwise "
            "Positive Prompt) - edit the text to override that row's "
            "prompt, or click ✕ to skip it entirely. Neither ever touches "
            "the source CSV file."
        ))

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        for row_num, text in prompts:
            self._add_row(row_num, text)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_row(self, row_num, text):
        item = QListWidgetItem()
        row_widget = _PromptRowWidget(row_num, text)
        item.setSizeHint(row_widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, row_widget)
        row_widget.remove_button.clicked.connect(lambda: self._remove_row(item))

    def _remove_row(self, item):
        self.list_widget.takeItem(self.list_widget.row(item))

    @property
    def current_prompts(self):
        """{row_num: current_text} for whatever rows remain."""
        result = {}
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            result[widget.row_num] = widget.text_edit.toPlainText()
        return result
