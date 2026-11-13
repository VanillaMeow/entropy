"""Queue, batch and setup state for one desktop session, independent of the UI."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QStandardPaths, Signal

from src.core.config import UpscaleRequest
from src.core.events import (
    Complete,
    Error,
    ImageError,
    ModelDownload,
    ModelReady,
    Progress,
    RuntimeReady,
    Saved,
    Started,
    Status,
    WorkerEvent,
)
from src.core.imaging import SUPPORTED_SUFFIXES
from src.core.models import DEFAULT_PROFILE
from src.logic.image_queue import EntryState, ImageQueue, QueueEntry

if TYPE_CHECKING:
    from src.application import Entropy

TILE_SIZES = frozenset({32, 64, 128, 256, 512})
MIN_SCALE, MAX_SCALE = 0.1, 4.0
MAX_PADDING = 128
MAX_LOG_LINES = 500


class Session(QObject):
    """Own the queue, preferences and worker lifecycle; notify the UI through signals.

    ``stateChanged`` covers busy, status and readiness, ``selectionChanged`` the
    selected image and its result, ``settingsChanged`` the user preferences and
    ``diagnosticsChanged`` the log.
    """

    stateChanged = Signal()
    settingsChanged = Signal()
    selectionChanged = Signal()
    diagnosticsChanged = Signal()

    def __init__(self, app: Entropy) -> None:
        super().__init__()
        self.app = app
        self.queue = ImageQueue(self)
        self.queue.changed.connect(self.stateChanged)
        app.worker.received.connect(self.handle_event)
        app.worker.diagnostic.connect(self.log)
        app.worker.finished.connect(self.handle_finished)

        self.request: UpscaleRequest | None = None
        self.preparing = False
        self.model_ready = False
        self.runtime_ready = False
        self.selected = -1
        self.progress = 0.0
        self.indeterminate = False
        self.has_error = False
        self.status = self.tr('Ready when you are')
        self.model_status = self.tr('Installs automatically · 4.9 MB')
        self.logs: list[str] = []
        self._terminal_event = False
        self._start_time = 0.0

        settings = app.settings
        pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        self._output = settings.get('output', str(Path(pictures or Path.home()) / 'Upscaled'))
        tile = settings.get('tileSize', 128)
        self._tile = tile if tile in TILE_SIZES else 128
        padding = settings.get('padding', 16)
        self._padding = padding if 0 <= padding <= MAX_PADDING else 16
        scale = settings.get('outputScale', MAX_SCALE)
        self._output_scale = scale if MIN_SCALE <= scale <= MAX_SCALE else MAX_SCALE

    # Derived state

    @property
    def busy(self) -> bool:
        """Whether a worker is running, for setup or a batch."""
        return self.app.worker.running

    @property
    def can_edit(self) -> bool:
        """Whether the queue and preferences may change; setup does not lock them."""
        return not self.busy or self.preparing

    @property
    def can_start(self) -> bool:
        """Whether a batch can start; resizing at or below 1x needs no model or GPU."""
        return (
            not self.busy
            and self.queue.count > 0
            and bool(self._output.strip())
            and (self._output_scale <= 1 or (self.model_ready and self.runtime_ready))
        )

    @property
    def selected_entry(self) -> QueueEntry | None:
        """The queue entry shown in the comparison view, if any."""
        return self.queue.entries[self.selected] if self.selected >= 0 else None

    @property
    def output_path(self) -> Path:
        """The output folder as an absolute path."""
        return Path(self._output).expanduser().resolve()

    # Preferences

    @property
    def output_directory(self) -> str:
        """The output folder exactly as the user entered it."""
        return self._output

    @output_directory.setter
    def output_directory(self, value: str) -> None:
        if self.can_edit and value != self._output:
            self._output = value
            self.settingsChanged.emit()
            self.stateChanged.emit()

    @property
    def output_scale(self) -> float:
        """Requested output size relative to the source, from 0.1x to 4x."""
        return self._output_scale

    @output_scale.setter
    def output_scale(self, value: float) -> None:
        valid = math.isfinite(value) and MIN_SCALE <= value <= MAX_SCALE
        if self.can_edit and valid and value != self._output_scale:
            self._output_scale = value
            self.settingsChanged.emit()
            self.stateChanged.emit()

    @property
    def tile_size(self) -> int:
        """Inference tile edge in pixels."""
        return self._tile

    @tile_size.setter
    def tile_size(self, value: int) -> None:
        if self.can_edit and value in TILE_SIZES:
            self._tile = value
            self.settingsChanged.emit()

    @property
    def padding(self) -> int:
        """Overlap around each tile, which hides seams."""
        return self._padding

    @padding.setter
    def padding(self, value: int) -> None:
        if self.can_edit and 0 <= value <= MAX_PADDING:
            self._padding = value
            self.settingsChanged.emit()

    def save_settings(self) -> None:
        """Persist the user's preferences."""
        settings = self.app.settings
        settings.set('output', self._output)
        settings.set('tileSize', self._tile)
        settings.set('padding', self._padding)
        settings.set('outputScale', self._output_scale)

    # Queue

    def select(self, row: int) -> None:
        """Select an image for before/after comparison, or -1 for none."""
        if -1 <= row < self.queue.count and row != self.selected:
            self.selected = row
            self.selectionChanged.emit()

    def add_paths(self, paths: list[Path]) -> None:
        """Expand folders non-recursively and append supported images."""
        if not self.can_edit:
            return
        try:
            candidates = [
                child.expanduser().resolve()
                for path in paths
                for child in (sorted(path.iterdir()) if path.is_dir() else [path])
            ]
            self.queue.append(
                [
                    path
                    for path in candidates
                    if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
                ]
            )
        except OSError as exc:
            self.report_error(self.tr('Could not add images: {error}').format(error=exc))
            return
        if self.selected < 0 and self.queue.count:
            self.select(0)
        self.status = (
            self.tr('1 image ready')
            if self.queue.count == 1
            else self.tr('{count} images ready').format(count=self.queue.count)
        )
        self.has_error = False
        self.stateChanged.emit()

    def remove_selected(self) -> None:
        """Remove the selected image without deleting its files."""
        if not self.can_edit or self.selected < 0:
            return
        row = self.selected
        self.selected = -1
        self.queue.remove(row)
        self.select(min(row, self.queue.count - 1))
        self.selectionChanged.emit()

    def clear_queue(self) -> None:
        """Clear the queue without deleting source or output files."""
        if self.can_edit:
            self.selected = -1
            self.queue.clear()
            self.selectionChanged.emit()

    # Worker

    def prepare(self) -> None:
        """Install the default model and probe GPU support in the worker."""
        if self.busy:
            return
        self.preparing = True
        self._terminal_event = False
        self.has_error = False
        self.status = self.tr('Preparing your workspace…')
        self.app.worker.start('prepare')
        self.stateChanged.emit()

    def start_batch(self) -> None:
        """Snapshot the queue and preferences, then start the worker on them."""
        if not self.can_start:
            return
        try:
            request = UpscaleRequest(
                images=tuple(entry.path for entry in self.queue.entries),
                output_dir=self.output_path,
                profile=DEFAULT_PROFILE,
                output_scale=self._output_scale,
                tile_size=self._tile,
                padding=self._padding,
            )
        except (OSError, ValueError) as exc:
            self.report_error(str(exc))
            return
        self.request = request
        self.preparing = False
        self._terminal_event = False
        self.has_error = False
        for row in range(self.queue.count):
            self.queue.update_entry(row, state=EntryState.QUEUED)
        self.selectionChanged.emit()
        self.progress, self.indeterminate = 0.0, True
        self.status = (
            self.tr('Resizing images…')
            if request.output_scale <= 1
            else self.tr('Warming up the GPU…')
        )
        self._start_time = time.monotonic()
        self.app.worker.start('job', request)
        self.stateChanged.emit()

    def cancel(self) -> None:
        """Stop the native worker immediately."""
        self.app.worker.cancel()

    def handle_event(self, event: WorkerEvent) -> None:
        """Apply one event reported by the worker."""
        match event:
            case ModelDownload(done=done, total=total):
                self.progress = done / total
                self.indeterminate = False
                self.model_status = self.tr('Downloading… {percent}%').format(
                    percent=round(self.progress * 100)
                )
                self.status = self.tr(
                    'Installing your enhancement model. This only downloads once.'
                )
            case ModelReady():
                self.model_ready = True
                self.model_status = self.tr('Ready for offline use')
            case RuntimeReady(available=available, runtime_path=runtime_path):
                self._terminal_event = True
                self.runtime_ready = available
                self.log(f'GPU runtime: {"ready" if available else "unavailable"}')
                if available:
                    self.status = self.tr('Ready when you are')
                else:
                    self._set_error(self.tr('GPU setup is required. Open diagnostics for details.'))
                    self.log('Build the GPU runtime: uv run python scripts/build_mnn.py')
                if runtime_path:
                    self.log(f'MNN runtime: {runtime_path}')
            case Status(message=message):
                self.status = message
            case Started(index=index, source=source):
                self.queue.update_entry(index, state=EntryState.PROCESSING)
                self.status = self.tr('Processing {name}…').format(name=source.name)
            case Progress(index=index, done=done, total=total) if self.request:
                self._show_progress(index, done, total, len(self.request.images))
            case Saved(index=index, output=output, output_scale=output_scale):
                self.queue.update_entry(
                    index, state=EntryState.DONE, output=output, output_scale=output_scale
                )
                self.log(f'Saved: {output}')
                self.selectionChanged.emit()
            case ImageError(index=index, message=message):
                self.queue.update_entry(index, state=EntryState.FAILED, error=message)
                self.log(message)
            case Error(message=message):
                self._terminal_event = True
                self._set_error(message)
                if self.preparing:
                    self.runtime_ready = False
            case Complete(succeeded=succeeded, failed=failed):
                self._terminal_event = True
                self.progress, self.indeterminate = 1.0, False
                self.has_error = failed > 0
                self.status = self.tr('Finished · {saved} saved · {failed} failed').format(
                    saved=succeeded, failed=failed
                )
            case Progress():
                # Progress without a batch belongs to a run that already finished
                pass
        self.stateChanged.emit()

    def handle_finished(self, code: int, cancelled: bool) -> None:
        """Settle the queue and clean up after the worker exits."""
        self.indeterminate = False
        if cancelled:
            self.status = (
                self.tr('Setup cancelled. Retry when you’re ready.')
                if self.preparing
                else self.tr('Cancelled. Your completed images are saved.')
            )
        elif not self._terminal_event:
            self._set_error(self.tr('The worker stopped unexpectedly. See diagnostics.'))
            self.log(f'Worker exit code: {code}')
        if self.request:
            unfinished = EntryState.CANCELLED if cancelled else EntryState.NOT_COMPLETED
            for row, entry in enumerate(self.queue.entries):
                if entry.state in {EntryState.QUEUED, EntryState.PROCESSING}:
                    self.queue.update_entry(row, state=unfinished)
            try:
                self.request.staging_path.unlink(missing_ok=True)
            except OSError as exc:
                self.log(f'Could not remove scratch output: {exc}')
        self.request = None
        self.preparing = False
        self.selectionChanged.emit()
        self.stateChanged.emit()

    # Messages

    def report_error(self, message: str) -> None:
        """Show an error in the status bar and the diagnostics log."""
        self._set_error(message)
        self.stateChanged.emit()

    def log(self, message: str) -> None:
        """Append text to the diagnostics log, keeping the most recent lines."""
        self.logs.extend(message.rstrip().splitlines())
        del self.logs[:-MAX_LOG_LINES]
        self.diagnosticsChanged.emit()

    def _set_error(self, message: str) -> None:
        self.status, self.has_error = message, True
        self.log(message)

    def _show_progress(self, index: int, done: int, total: int, images: int) -> None:
        self.indeterminate = False
        self.progress = (index + done / total) / images
        elapsed = time.monotonic() - self._start_time
        remaining = elapsed * (1 - self.progress) / self.progress
        self.status = self.tr(
            'Image {current} of {total} · about {seconds} seconds remaining'
        ).format(current=index + 1, total=images, seconds=max(1, round(remaining)))
