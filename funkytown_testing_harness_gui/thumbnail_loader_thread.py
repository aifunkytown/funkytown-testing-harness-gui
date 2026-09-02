"""Background loading of the Results tab's gallery thumbnails, so selecting
a run with a lot of images doesn't freeze the window while every file is
read and scaled from disk.

Only the read-and-scale step happens here - QImage is safe to build off the
GUI thread, unlike QPixmap/QPainter/QIcon, which the caller's
thumbnail_ready slot handles instead.
"""

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QImage


class ThumbnailLoaderThread(QThread):
    # index into the path list this loader was given, the path itself (so a
    # caller can tell a stale loader's results apart from the currently
    # selected run's), and the scaled image - null if that file couldn't be
    # read as an image.
    thumbnail_ready = Signal(int, str, QImage)
    finished_loading = Signal()

    def __init__(self, paths, icon_size, parent=None):
        super().__init__(parent)
        self._paths = paths
        self._icon_size = icon_size

    def run(self):
        for i, path in enumerate(self._paths):
            image = QImage(str(path))
            if not image.isNull():
                image = image.scaled(self._icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.thumbnail_ready.emit(i, str(path), image)
        self.finished_loading.emit()
