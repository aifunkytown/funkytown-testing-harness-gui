"""Dialog for building one LoRA's list of weights to sweep - lora_test.py
queues one run per weight given (or, in combined mode, treats this as one
axis of the cartesian product across every LoRA's weights).
"""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class LoraWeightsDialog(QDialog):
    """Configure one LoRA's weight list. Result available via .lora_name and
    .weights after exec() returns QDialog.Accepted."""

    def __init__(self, lora_name, parent=None, initial_weights=None):
        super().__init__(parent)
        self.setWindowTitle(f"Weights: {lora_name}")
        self.setMinimumWidth(360)
        self.lora_name = lora_name

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{lora_name}</b>"))
        layout.addWidget(QLabel("One queued run per weight (or one axis of the combination, in combined mode)."))

        self.weights_list = QListWidget()
        for weight in (initial_weights or [1.0]):
            self.weights_list.addItem(QListWidgetItem(str(weight)))
        layout.addWidget(self.weights_list)

        add_row = QHBoxLayout()
        self.new_weight_spin = QDoubleSpinBox()
        # Range's minimum is reserved as a "nothing entered yet" sentinel
        # (shown blank via setSpecialValueText) so the box doesn't default
        # to a specific weight - -10.0 itself stays enterable as a real value.
        self.new_weight_spin.setRange(-10.1, 10.0)
        self.new_weight_spin.setSingleStep(1.0)
        self.new_weight_spin.setSpecialValueText(" ")
        self.new_weight_spin.setValue(self.new_weight_spin.minimum())
        add_row.addWidget(self.new_weight_spin, 1)
        add_button = QPushButton("+ Add weight")
        add_button.clicked.connect(self._add_weight)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)

        remove_button = QPushButton("Remove selected weight")
        remove_button.clicked.connect(self._remove_selected_weight)
        layout.addWidget(remove_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_weight(self):
        if self.new_weight_spin.value() <= self.new_weight_spin.minimum():
            QMessageBox.information(self, "No weight entered", "Enter a weight value first.")
            return
        self.weights_list.addItem(QListWidgetItem(str(self.new_weight_spin.value())))
        self.new_weight_spin.setValue(self.new_weight_spin.minimum())

    def _remove_selected_weight(self):
        if self.weights_list.count() <= 1:
            QMessageBox.information(self, "Can't remove", "A LoRA needs at least one weight.")
            return
        row = self.weights_list.currentRow()
        if row >= 0:
            self.weights_list.takeItem(row)

    def _on_accept(self):
        self.weights = [float(self.weights_list.item(i).text()) for i in range(self.weights_list.count())]
        self.accept()
