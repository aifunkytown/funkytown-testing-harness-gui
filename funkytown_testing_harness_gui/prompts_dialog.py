"""Popup for viewing/editing the Testing tab's prompt list - each existing
prompt is its own row with a delete button; a text box at the bottom adds
brand new prompts. Existing rows are view/delete only (not directly text-
editable) - to change a prompt's wording, remove it and add the new
version."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class _PromptRow(QWidget):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.remove_button = QToolButton()
        self.remove_button.setText("✕")
        self.remove_button.setAutoRaise(True)
        self.remove_button.setToolTip("Remove this prompt")
        layout.addWidget(self.remove_button)


class PromptsDialog(QDialog):
    def __init__(self, prompts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Prompts")
        self.resize(560, 460)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Each prompt is its own row - click ✕ to remove one. Type "
            "a new prompt below and press Add (or Enter) to add it."
        ))

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)

        for text in prompts:
            self._add_row(text)

        add_row = QHBoxLayout()
        self.new_prompt_edit = QLineEdit()
        self.new_prompt_edit.setPlaceholderText("Type a new prompt...")
        self.new_prompt_edit.returnPressed.connect(self._on_add_clicked)
        add_row.addWidget(self.new_prompt_edit, 1)
        add_button = QPushButton("Add")
        add_button.clicked.connect(self._on_add_clicked)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_row(self, text):
        item = QListWidgetItem()
        row_widget = _PromptRow(text)
        item.setSizeHint(row_widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, row_widget)
        row_widget.remove_button.clicked.connect(lambda: self._remove_row(item))

    def _remove_row(self, item):
        self.list_widget.takeItem(self.list_widget.row(item))

    def _on_add_clicked(self):
        text = self.new_prompt_edit.text().strip()
        if not text:
            return
        self._add_row(text)
        self.new_prompt_edit.clear()

    @property
    def prompts(self):
        result = []
        for i in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(i))
            result.append(widget.label.text())
        return result
