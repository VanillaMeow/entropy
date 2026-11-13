"""The QML view model: a thin, typed face over the session for Qt Quick."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QAbstractItemModel, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QmlElement, QmlUncreatable

from entropy.logic.image_queue import preview_url
from entropy.ui.preview import image_aspect

if TYPE_CHECKING:
    from entropy.application import Entropy

QML_IMPORT_NAME = 'Entropy'
QML_IMPORT_MAJOR_VERSION = 1

# Shown before any result exists, matching the default 4x model
DEFAULT_RESULT_SCALE = 4.0

# A typical photo shape, used while nothing is selected
DEFAULT_ASPECT = 1.5

# Matches the floor the application applies to the system font
MIN_FONT_SIZE = 12


@QmlElement
@QmlUncreatable('The application creates its controller')
class AppController(QObject):
    """Expose session state and actions to QML; holds no state of its own but the theme.

    Writable properties use Property's explicit getter/setter form, because
    strict pyright reports the ``@x.setter`` pattern as a redeclaration.
    """

    stateChanged = Signal()
    settingsChanged = Signal()
    selectionChanged = Signal()
    diagnosticsChanged = Signal()

    def __init__(self, app: Entropy) -> None:
        super().__init__()
        self.app = app

        # Forward the session's signals, they drive every binding below
        session = app.session
        session.stateChanged.connect(self.stateChanged)
        session.settingsChanged.connect(self.settingsChanged)
        session.selectionChanged.connect(self.selectionChanged)
        session.diagnosticsChanged.connect(self.diagnosticsChanged)

        # Follow the desktop's color scheme until the user picks a theme
        default_dark = QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
        self._dark = app.settings.get('darkTheme', default_dark)

    def save_settings(self) -> None:
        """Persist the theme, the only preference the UI owns."""
        self.app.settings.set('darkTheme', self._dark)

    # Queue and status

    @Property(QAbstractItemModel, constant=True)
    def queueModel(self) -> QAbstractItemModel:
        return self.app.session.queue

    @Property(int, notify=stateChanged)
    def queueCount(self) -> int:
        return self.app.session.queue.count

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self.app.session.busy

    @Property(bool, notify=stateChanged)
    def preparing(self) -> bool:
        return self.app.session.preparing

    @Property(bool, notify=stateChanged)
    def canEdit(self) -> bool:
        return self.app.session.can_edit

    @Property(bool, notify=stateChanged)
    def modelReady(self) -> bool:
        return self.app.session.model_ready

    @Property(bool, notify=stateChanged)
    def canStart(self) -> bool:
        return self.app.session.can_start

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self.app.session.status

    @Property(str, notify=stateChanged)
    def modelStatus(self) -> str:
        return self.app.session.model_status

    @Property(float, notify=stateChanged)
    def progress(self) -> float:
        return self.app.session.progress

    @Property(bool, notify=stateChanged)
    def indeterminate(self) -> bool:
        return self.app.session.indeterminate

    @Property(bool, notify=stateChanged)
    def hasError(self) -> bool:
        return self.app.session.has_error

    @Property(str, notify=diagnosticsChanged)
    def diagnostics(self) -> str:
        return '\n'.join(self.app.session.logs)

    @Property(float, constant=True)
    def bodyFontSize(self) -> float:
        return max(MIN_FONT_SIZE, QGuiApplication.font().pointSizeF())

    # Selection

    @Property(int, notify=selectionChanged)
    def selectedIndex(self) -> int:
        return self.app.session.selected

    @Property(str, notify=selectionChanged)
    def selectedName(self) -> str:
        entry = self.app.session.selected_entry
        return entry.path.name if entry else ''

    @Property(QUrl, notify=selectionChanged)
    def originalUrl(self) -> QUrl:
        entry = self.app.session.selected_entry
        return QUrl.fromLocalFile(str(entry.path)) if entry else QUrl()

    @Property(QUrl, notify=selectionChanged)
    def originalPreviewUrl(self) -> QUrl:
        entry = self.app.session.selected_entry
        return preview_url(entry.path if entry else None)

    @Property(QUrl, notify=selectionChanged)
    def resultUrl(self) -> QUrl:
        entry = self.app.session.selected_entry
        return QUrl.fromLocalFile(str(entry.output)) if entry and entry.output else QUrl()

    @Property(bool, notify=selectionChanged)
    def hasResult(self) -> bool:
        entry = self.app.session.selected_entry
        return entry is not None and entry.output is not None

    @Property(float, notify=selectionChanged)
    def resultScale(self) -> float:
        entry = self.app.session.selected_entry
        return (entry.output_scale if entry else None) or DEFAULT_RESULT_SCALE

    @Property(float, notify=selectionChanged)
    def previewAspect(self) -> float:
        entry = self.app.session.selected_entry
        return image_aspect(entry.path) if entry else DEFAULT_ASPECT

    # Preferences

    @Property(QUrl, notify=settingsChanged)
    def outputUrl(self) -> QUrl:
        return QUrl.fromLocalFile(str(self.app.session.output_path))

    def _output_directory(self) -> str:
        return self.app.session.output_directory

    def _set_output_directory(self, value: str) -> None:
        self.app.session.output_directory = value

    outputDirectory = Property(
        str, _output_directory, _set_output_directory, notify=settingsChanged
    )

    def _output_scale(self) -> float:
        return self.app.session.output_scale

    def _set_output_scale(self, value: float) -> None:
        self.app.session.output_scale = value

    outputScale = Property(float, _output_scale, _set_output_scale, notify=settingsChanged)

    def _tile_size(self) -> int:
        return self.app.session.tile_size

    def _set_tile_size(self, value: int) -> None:
        self.app.session.tile_size = value

    tileSize = Property(int, _tile_size, _set_tile_size, notify=settingsChanged)

    def _padding(self) -> int:
        return self.app.session.padding

    def _set_padding(self, value: int) -> None:
        self.app.session.padding = value

    padding = Property(int, _padding, _set_padding, notify=settingsChanged)

    def _dark_theme(self) -> bool:
        return self._dark

    def _set_dark_theme(self, value: bool) -> None:
        if value != self._dark:
            self._dark = value
            self.settingsChanged.emit()

    darkTheme = Property(bool, _dark_theme, _set_dark_theme, notify=settingsChanged)

    # Actions

    @Slot(int)
    def select(self, row: int) -> None:
        """Select an image for before/after comparison."""
        self.app.session.select(row)

    @Slot('QVariantList')
    def addUrls(self, urls: list[QUrl | str]) -> None:
        """Accept local file and folder URLs from native dialogs or drag and drop."""
        # Drag and drop hands over strings, dialogs hand over QUrl objects
        paths: list[Path] = []
        for value in urls:
            url = value if isinstance(value, QUrl) else QUrl(value)
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))

        self.app.session.add_paths(paths)

    @Slot()
    def removeSelected(self) -> None:
        """Remove the selected image without deleting its files."""
        self.app.session.remove_selected()

    @Slot()
    def clearQueue(self) -> None:
        """Clear the queue without deleting source or output files."""
        self.app.session.clear_queue()

    @Slot(QUrl)
    def setOutputFolder(self, url: QUrl) -> None:
        """Apply a folder URL returned by the native portal."""
        if url.isLocalFile():
            self.app.session.output_directory = url.toLocalFile()

    @Slot()
    def prepare(self) -> None:
        """Install the default model and probe GPU support."""
        self.app.session.prepare()

    @Slot()
    def startBatch(self) -> None:
        """Start processing the queue."""
        self.app.session.start_batch()

    @Slot()
    def cancel(self) -> None:
        """Stop the native worker immediately."""
        self.app.session.cancel()

    @Slot()
    def openOutput(self) -> None:
        """Reveal the output directory in the desktop file manager."""
        path = self.app.session.output_path

        if not path.is_dir():
            self.app.session.report_error(self.tr('The output folder has not been created yet.'))
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.app.session.report_error(self.tr('Could not open the output folder.'))

    @Slot()
    def shutdown(self) -> None:
        """Reap the worker and persist preferences before the window closes."""
        self.app.shutdown()
