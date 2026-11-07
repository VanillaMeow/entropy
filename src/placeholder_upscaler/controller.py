"""Typed Qt Quick view model, independent of the visual component tree."""

import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractItemModel,
    QObject,
    QSettings,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QmlElement, QmlUncreatable

from placeholder_upscaler.config import Backend, UpscaleRequest
from placeholder_upscaler.imaging import SUPPORTED_SUFFIXES
from placeholder_upscaler.models import DEFAULT_PROFILE
from placeholder_upscaler.preview import image_aspect, preview_url
from placeholder_upscaler.process import WorkerProcess
from placeholder_upscaler.queue import ImageQueue

QML_IMPORT_NAME = "Upscaler.Backend"
QML_IMPORT_MAJOR_VERSION = 1


@QmlElement
@QmlUncreatable("The application creates its controller")
class AppController(QObject):
    """Expose application state and explicit actions to declarative QML views."""

    stateChanged = Signal()
    settingsChanged = Signal()
    selectionChanged = Signal()
    diagnosticsChanged = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        settings: QSettings | None = None,
        start_setup: bool = True,
    ) -> None:
        super().__init__(parent)
        # Preserve preferences saved before the Entropy rename.
        self._settings = (
            settings
            if settings is not None
            else QSettings("PlaceholderUpscaler", "PlaceholderUpscaler")
        )
        self._queue = ImageQueue(self)
        self._queue.changed.connect(self.stateChanged)
        self._worker = WorkerProcess(self)
        self._worker.event.connect(self._handle_event)
        self._worker.diagnostic.connect(self._log)
        self._worker.finished.connect(self._finished)
        self._scratch: TemporaryDirectory[str] | None = None
        self._request: UpscaleRequest | None = None
        self._preparing = False
        self._model_ready = False
        self._backends: dict[str, bool] = {}
        self._selected = -1
        self._progress = 0.0
        self._indeterminate = False
        self._error = False
        self._status = self.tr("Ready when you are")
        self._model_status = self.tr("Installs automatically · 4.9 MB")
        self._backend_status = self.tr("Checking GPU support…")
        self._logs: list[str] = []
        self._terminal_event = False
        self._start_time = 0.0
        pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        self._output = str(
            self._settings.value("output", str(Path(pictures or Path.home()) / "Upscaled"))
        )
        self._backend = str(self._settings.value("backend", Backend.VULKAN.value))
        if self._backend not in {backend.value for backend in Backend}:
            self._backend = Backend.VULKAN.value
        self._tile = int(self._settings.value("tileSize", 128))
        self._padding = int(self._settings.value("padding", 16))
        default_dark = QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Light
        self._dark = self._settings.value("darkTheme", default_dark, type=bool)
        if start_setup:
            QTimer.singleShot(0, self.prepare)

    @Property(QAbstractItemModel, constant=True)
    def queueModel(self) -> ImageQueue:
        return self._queue

    @Property(int, notify=stateChanged)
    def queueCount(self) -> int:
        return self._queue.count

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._worker.running

    @Property(bool, notify=stateChanged)
    def preparing(self) -> bool:
        return self._preparing

    @Property(bool, notify=stateChanged)
    def canEdit(self) -> bool:
        return not self.busy or self._preparing

    @Property(bool, notify=stateChanged)
    def modelReady(self) -> bool:
        return self._model_ready

    @Property(bool, notify=stateChanged)
    def canStart(self) -> bool:
        return (
            not self.busy
            and self._queue.count > 0
            and self._model_ready
            and bool(self._output.strip())
            and self._backends.get(self._backend, False)
        )

    @Property(str, notify=stateChanged)
    def statusText(self) -> str:
        return self._status

    @Property(str, notify=stateChanged)
    def modelStatus(self) -> str:
        return self._model_status

    @Property(str, notify=stateChanged)
    def backendStatus(self) -> str:
        return self._backend_status

    @Property("double", notify=stateChanged)
    def progress(self) -> float:
        return self._progress

    @Property("double", constant=True)
    def bodyFontSize(self) -> float:
        return max(12, QGuiApplication.font().pointSizeF())

    @Property(bool, notify=stateChanged)
    def indeterminate(self) -> bool:
        return self._indeterminate

    @Property(bool, notify=stateChanged)
    def hasError(self) -> bool:
        return self._error

    @Property(str, notify=diagnosticsChanged)
    def diagnostics(self) -> str:
        return "\n".join(self._logs)

    @Property(int, notify=selectionChanged)
    def selectedIndex(self) -> int:
        return self._selected

    @Property(str, notify=selectionChanged)
    def selectedName(self) -> str:
        return self._queue.entries[self._selected].path.name if self._selected >= 0 else ""

    @Property(QUrl, notify=selectionChanged)
    def originalUrl(self) -> QUrl:
        return (
            QUrl.fromLocalFile(str(self._queue.entries[self._selected].path))
            if self._selected >= 0
            else QUrl()
        )

    @Property(QUrl, notify=selectionChanged)
    def resultUrl(self) -> QUrl:
        entry = self._queue.entries[self._selected] if self._selected >= 0 else None
        return QUrl.fromLocalFile(str(entry.output)) if entry and entry.output else QUrl()

    @Property(bool, notify=selectionChanged)
    def hasResult(self) -> bool:
        return self._selected >= 0 and self._queue.entries[self._selected].output is not None

    @Property("double", notify=selectionChanged)
    def previewAspect(self) -> float:
        return image_aspect(
            self._queue.entries[self._selected].path if self._selected >= 0 else None
        )

    @Property(str, notify=settingsChanged)
    def outputDirectory(self) -> str:
        return self._output

    @Property(QUrl, notify=selectionChanged)
    def originalPreviewUrl(self) -> QUrl:
        return preview_url(
            self._queue.entries[self._selected].path if self._selected >= 0 else None
        )

    @outputDirectory.setter
    def outputDirectory(self, value: str) -> None:
        if self.canEdit and value != self._output:
            self._output = value
            self.settingsChanged.emit()
            self.stateChanged.emit()

    @Property(QUrl, notify=settingsChanged)
    def outputUrl(self) -> QUrl:
        return QUrl.fromLocalFile(str(Path(self._output).expanduser().resolve()))

    @Property(str, notify=settingsChanged)
    def backend(self) -> str:
        return self._backend

    @backend.setter
    def backend(self, value: str) -> None:
        if self.canEdit and value in {b.value for b in Backend} and value != self._backend:
            self._backend = value
            self.settingsChanged.emit()
            self.stateChanged.emit()

    @Property(int, notify=settingsChanged)
    def tileSize(self) -> int:
        return self._tile

    @tileSize.setter
    def tileSize(self, value: int) -> None:
        if self.canEdit and value in {32, 64, 128, 256, 512}:
            self._tile = value
            self.settingsChanged.emit()

    @Property(int, notify=settingsChanged)
    def padding(self) -> int:
        return self._padding

    @padding.setter
    def padding(self, value: int) -> None:
        if self.canEdit and 0 <= value <= 128:
            self._padding = value
            self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def darkTheme(self) -> bool:
        return self._dark

    @darkTheme.setter
    def darkTheme(self, value: bool) -> None:
        if value != self._dark:
            self._dark = value
            self.settingsChanged.emit()

    @Slot(int)
    def select(self, row: int) -> None:
        """Select an image for before/after comparison."""
        if -1 <= row < self._queue.count and row != self._selected:
            self._selected = row
            self.selectionChanged.emit()

    @Slot("QVariantList")
    def addUrls(self, urls: list[QUrl | str]) -> None:
        """Accept local file/folder URLs from native dialogs or drag and drop."""
        paths = []
        for value in urls:
            url = value if isinstance(value, QUrl) else QUrl(value)
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        self.add_paths(paths)

    def add_paths(self, paths: list[Path]) -> None:
        """Expand folders non-recursively and append supported images."""
        if not self.canEdit:
            return
        try:
            candidates = [
                child.expanduser().resolve()
                for path in paths
                for child in (sorted(path.iterdir()) if path.is_dir() else [path])
            ]
            self._queue.append(
                [
                    path
                    for path in candidates
                    if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
                ]
            )
            if self._selected < 0 and self._queue.count:
                self.select(0)
            self._status = (
                self.tr("1 image ready")
                if self._queue.count == 1
                else self.tr("{count} images ready").format(count=self._queue.count)
            )
            self._error = False
        except OSError as exc:
            self._set_error(self.tr("Could not add images: {error}").format(error=exc))
        self.stateChanged.emit()

    @Slot()
    def removeSelected(self) -> None:
        """Remove the selected image without deleting its files."""
        if not self.canEdit or self._selected < 0:
            return
        row = self._selected
        self._selected = -1
        self._queue.remove(row)
        self.select(min(row, self._queue.count - 1))
        self.selectionChanged.emit()

    @Slot()
    def clearQueue(self) -> None:
        """Clear the queue without deleting source or output files."""
        if self.canEdit:
            self._selected = -1
            self._queue.clear()
            self.selectionChanged.emit()

    @Slot(QUrl)
    def setOutputFolder(self, url: QUrl) -> None:
        """Apply a folder URL returned by the native portal."""
        if url.isLocalFile():
            self.outputDirectory = url.toLocalFile()

    @Slot()
    def prepare(self) -> None:
        """Install the default model and probe GPU support in the worker."""
        if self.busy:
            return
        self._preparing = True
        self._terminal_event = False
        self._error = False
        self._status = self.tr("Preparing your workspace…")
        self._backend_status = self.tr("Checking GPU support…")
        self._worker.start("--prepare")
        self.stateChanged.emit()

    @Slot()
    def startBatch(self) -> None:
        """Snapshot settings and start the isolated inference worker."""
        if not self.canStart:
            return
        try:
            request = UpscaleRequest(
                images=tuple(entry.path for entry in self._queue.entries),
                output_dir=Path(self._output).expanduser().resolve(),
                profile=DEFAULT_PROFILE,
                backend=Backend(self._backend),
                tile_size=self._tile,
                padding=self._padding,
            )
            self._scratch = TemporaryDirectory(prefix="entropy-")
            job = Path(self._scratch.name) / "job.json"
            job.write_text(request.model_dump_json(), encoding="utf-8")
            self._request = request
        except (OSError, ValueError) as exc:
            self._set_error(str(exc))
            self.stateChanged.emit()
            return
        self._preparing = False
        self._terminal_event = False
        self._error = False
        for row in range(self._queue.count):
            self._queue.update_entry(row, state="Queued")
        self.selectionChanged.emit()
        self._progress, self._indeterminate = 0.0, True
        self._status = self.tr("Warming up the GPU…")
        self._start_time = time.monotonic()
        self._worker.start(str(job))
        self.stateChanged.emit()

    @Slot()
    def cancel(self) -> None:
        """Stop the native worker immediately."""
        self._worker.cancel()

    @Slot()
    def openOutput(self) -> None:
        """Reveal the output directory in the desktop file manager."""
        path = Path(self._output).expanduser().resolve()
        if not path.is_dir():
            self._set_error(self.tr("The output folder has not been created yet."))
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self._set_error(self.tr("Could not open the output folder."))
        self.stateChanged.emit()

    def _set_error(self, message: str) -> None:
        self._status, self._error = message, True
        self._log(message)

    def _log(self, message: str) -> None:
        self._logs.extend(message.rstrip().splitlines())
        self._logs = self._logs[-500:]
        self.diagnosticsChanged.emit()

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "model_download":
            self._progress = event["done"] / event["total"]
            self._indeterminate = False
            self._model_status = self.tr("Downloading… {percent}%").format(
                percent=round(self._progress * 100)
            )
            self._status = self.tr("Installing your enhancement model. This only downloads once.")
        elif kind == "model_ready":
            self._model_ready = True
            self._model_status = self.tr("Ready for offline use")
        elif kind == "backends":
            self._terminal_event = True
            self._backends = event["available"]
            self._backend_status = " · ".join(
                f"{name}: {self.tr('ready') if ready else self.tr('unavailable')}"
                for name, ready in self._backends.items()
            )
            if not self._backends.get(self._backend, False):
                self._backend = next(
                    (name for name, ready in self._backends.items() if ready), self._backend
                )
                self.settingsChanged.emit()
            if any(self._backends.values()):
                self._status = self.tr("Ready when you are")
            else:
                self._set_error(self.tr("GPU setup is required. Open diagnostics for details."))
                self._log("Build the GPU runtime: uv run python scripts/build_mnn.py")
            if event.get("runtime_path"):
                self._log(f"MNN runtime: {event['runtime_path']}")
        elif kind == "status":
            self._status = event["message"]
        elif kind == "started":
            self._queue.update_entry(event["index"], state="Processing")
            self._status = self.tr("Upscaling {name}…").format(name=Path(event["source"]).name)
        elif kind == "progress" and self._request:
            self._indeterminate = False
            self._progress = (event["index"] + event["done"] / event["total"]) / len(
                self._request.images
            )
            remaining = (
                (time.monotonic() - self._start_time) * (1 - self._progress) / self._progress
            )
            self._status = self.tr(
                "Image {current} of {total} · about {seconds} seconds remaining"
            ).format(
                current=event["index"] + 1,
                total=len(self._request.images),
                seconds=max(1, round(remaining)),
            )
        elif kind == "saved":
            self._queue.update_entry(event["index"], state="Done", output=Path(event["output"]))
            self._log(f"Saved: {event['output']}")
            self.selectionChanged.emit()
        elif kind == "image_error":
            self._queue.update_entry(event["index"], state="Failed", error=event["message"])
            self._log(event["message"])
        elif kind == "error":
            self._terminal_event = True
            self._set_error(event["message"])
            if self._preparing:
                self._backends.clear()
                self._backend_status = self.tr("GPU check failed")
        elif kind == "complete":
            self._terminal_event = True
            self._progress, self._indeterminate = 1.0, False
            self._error = event["failed"] > 0
            self._status = self.tr("Finished · {saved} saved · {failed} failed").format(
                saved=event["succeeded"], failed=event["failed"]
            )
        self.stateChanged.emit()

    def _finished(self, code: int, cancelled: bool) -> None:
        self._indeterminate = False
        if cancelled:
            self._status = (
                self.tr("Setup cancelled. Retry when you’re ready.")
                if self._preparing
                else self.tr("Cancelled. Your completed images are saved.")
            )
        elif not self._terminal_event:
            self._set_error(self.tr("The worker stopped unexpectedly. See diagnostics."))
        if self._request:
            for row, entry in enumerate(self._queue.entries):
                if entry.state in {"Queued", "Processing"}:
                    self._queue.update_entry(
                        row, state="Cancelled" if cancelled else "Not completed"
                    )
            try:
                self._request.staging_path.unlink(missing_ok=True)
            except OSError as exc:
                self._log(f"Could not remove scratch output: {exc}")
        if self._scratch:
            self._scratch.cleanup()
            self._scratch = None
        self._request = None
        self._preparing = False
        self.selectionChanged.emit()
        self.stateChanged.emit()

    @Slot()
    def shutdown(self) -> None:
        """Reap the worker and persist user preferences before the UI exits."""
        self._worker.shutdown()
        for key, value in (
            ("output", self._output),
            ("backend", self._backend),
            ("tileSize", self._tile),
            ("padding", self._padding),
            ("darkTheme", self._dark),
        ):
            self._settings.setValue(key, value)
