"""In-app viewer for a logged run's output images - a filename list next to
a scaled preview, so browsing a run's results never needs the OS file
browser. Takes a plain list of image paths (a directory snapshot the caller
already resolved) - this dialog doesn't touch the filesystem itself beyond
loading the images it's given."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class ResultImagesDialog(QDialog):
    def __init__(self, title, image_paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Results: {title}")
        self.resize(760, 520)
        self._image_paths = list(image_paths)

        layout = QVBoxLayout(self)

        if not self._image_paths:
            layout.addWidget(QLabel(
                "No output images found yet for this run - if it's still in "
                "progress, reopen this later; this never polls ComfyUI, only "
                "shows whatever's on disk right now."
            ))
            self.file_list = None
            self.preview_label = None
        else:
            splitter = QSplitter(Qt.Horizontal)

            self.file_list = QListWidget()
            for path in self._image_paths:
                item = QListWidgetItem(path.name)
                item.setData(Qt.UserRole, str(path))
                self.file_list.addItem(item)
            self.file_list.currentItemChanged.connect(self._on_selection_changed)
            splitter.addWidget(self.file_list)

            preview_container = QWidget()
            preview_layout = QVBoxLayout(preview_container)
            self.preview_label = QLabel("Select an image to preview it.")
            self.preview_label.setAlignment(Qt.AlignCenter)
            self.preview_label.setMinimumSize(300, 300)
            preview_layout.addWidget(self.preview_label, 1)
            splitter.addWidget(preview_container)

            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            layout.addWidget(splitter, 1)

            self.file_list.setCurrentRow(0)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _on_selection_changed(self, current, _previous):
        if current is None or self.preview_label is None:
            return
        path = current.data(Qt.UserRole)
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview_label.setText(f"Could not load image:\n{path}")
            return
        scaled = pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.file_list is not None and self.file_list.currentItem() is not None:
            self._on_selection_changed(self.file_list.currentItem(), None)
