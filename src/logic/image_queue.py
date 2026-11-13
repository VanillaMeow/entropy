"""The image queue, exposed to Qt Quick as a native list model."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, override

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QUrl,
    Signal,
)

# Registered by the UI as the image provider that decodes preview_url() tokens
PREVIEW_PROVIDER = 'preview'

type ModelIndex = QModelIndex | QPersistentModelIndex


class EntryState(StrEnum):
    """Processing state of one image; QML compares and translates these values."""

    READY = 'Ready'
    QUEUED = 'Queued'
    PROCESSING = 'Processing'
    DONE = 'Done'
    FAILED = 'Failed'
    CANCELLED = 'Cancelled'
    NOT_COMPLETED = 'Not completed'


@dataclass
class QueueEntry:
    """Source, output, and processing state for one image."""

    path: Path
    state: EntryState = EntryState.READY
    output: Path | None = None
    output_scale: float | None = None
    error: str = ''


def preview_url(path: Path | None) -> QUrl:
    """Encode a local path as an unambiguous image-provider URL."""
    if path is None:
        return QUrl()

    # Base64 keeps slashes, spaces and non-ASCII names intact inside the URL
    token = base64.urlsafe_b64encode(str(path).encode()).decode('ascii')
    return QUrl(f'image://{PREVIEW_PROVIDER}/{token}')


def preview_path(token: str) -> Path:
    """Decode a token produced by preview_url()."""
    return Path(base64.urlsafe_b64decode(token).decode())


class ImageQueue(QAbstractListModel):
    """Provide stable, explicit roles to reusable QML thumbnail delegates."""

    changed = Signal()

    # QML reads each entry through these role names, in this order
    _NAMES: ClassVar = ('fileName', 'sourceUrl', 'outputUrl', 'state', 'errorText', 'previewUrl')
    _ROLES: ClassVar = {
        Qt.ItemDataRole.UserRole + offset: QByteArray(name.encode())
        for offset, name in enumerate(_NAMES)
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.entries: list[QueueEntry] = []

    def _count(self) -> int:
        return len(self.entries)

    count = Property(int, _count, notify=changed)

    # Qt model interface

    @override
    def rowCount(self, parent: ModelIndex | None = None) -> int:
        # A flat list, so only the invisible root has rows
        return 0 if parent is not None and parent.isValid() else len(self.entries)

    @override
    def roleNames(self) -> dict[int, QByteArray]:
        return self._ROLES

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None

        # Ordered to match _NAMES, so a role maps straight to its position
        entry = self.entries[index.row()]
        values = (
            entry.path.name,
            QUrl.fromLocalFile(str(entry.path)),
            QUrl.fromLocalFile(str(entry.output)) if entry.output else QUrl(),
            entry.state.value,
            entry.error,
            preview_url(entry.path),
        )

        offset = role - Qt.ItemDataRole.UserRole
        return values[offset] if 0 <= offset < len(values) else None

    # Queue editing

    def append(self, paths: list[Path]) -> None:
        """Insert unique file paths while retaining the existing order."""
        existing = {entry.path for entry in self.entries}
        additions: list[QueueEntry] = []
        for path in paths:
            if path not in existing:
                additions.append(QueueEntry(path))
                existing.add(path)

        if not additions:
            return

        first = len(self.entries)
        self.beginInsertRows(QModelIndex(), first, first + len(additions) - 1)
        self.entries.extend(additions)
        self.endInsertRows()
        self.changed.emit()

    def remove(self, row: int) -> None:
        """Remove one queue entry."""
        self.beginRemoveRows(QModelIndex(), row, row)
        del self.entries[row]
        self.endRemoveRows()
        self.changed.emit()

    def clear(self) -> None:
        """Clear the queue using a model reset."""
        self.beginResetModel()
        self.entries.clear()
        self.endResetModel()
        self.changed.emit()

    def update_entry(
        self,
        row: int,
        *,
        state: EntryState,
        output: Path | None = None,
        output_scale: float | None = None,
        error: str = '',
    ) -> None:
        """Publish processing changes for exactly one delegate."""
        entry = self.entries[row]
        entry.state = state
        entry.output = output
        entry.output_scale = output_scale
        entry.error = error

        index = self.index(row)
        self.dataChanged.emit(index, index, list(self._ROLES))
