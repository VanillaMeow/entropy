"""The image queue exposed to Qt Quick as a native list model."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, Qt, QUrl, Signal

from .preview import preview_url


@dataclass
class QueueEntry:
    """Source, output, and processing state for one image."""

    path: Path
    state: str = "Ready"
    output: Path | None = None
    output_scale: float | None = None
    error: str = ""


class ImageQueue(QAbstractListModel):
    """Provide stable, explicit roles to reusable QML thumbnail delegates."""

    changed = Signal()
    _names = ("fileName", "sourceUrl", "outputUrl", "state", "errorText", "previewUrl")
    _roles = {int(Qt.ItemDataRole.UserRole) + i: name.encode() for i, name in enumerate(_names)}

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.entries: list[QueueEntry] = []

    @Property(int, notify=changed)
    def count(self) -> int:
        """Number of images in the queue."""
        return len(self.entries)

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.entries)

    def roleNames(self) -> dict[int, bytes]:
        return self._roles

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        entry = self.entries[index.row()]
        values = (
            entry.path.name,
            QUrl.fromLocalFile(str(entry.path)),
            QUrl.fromLocalFile(str(entry.output)) if entry.output else QUrl(),
            entry.state,
            entry.error,
            preview_url(entry.path),
        )
        offset = role - int(Qt.ItemDataRole.UserRole)
        return values[offset] if 0 <= offset < len(values) else None

    def append(self, paths: list[Path]) -> None:
        """Insert unique file paths while retaining the existing order."""
        existing = {entry.path for entry in self.entries}
        additions = []
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
        state: str,
        output: Path | None = None,
        output_scale: float | None = None,
        error: str = "",
    ) -> None:
        """Publish processing changes for exactly one delegate."""
        entry = self.entries[row]
        entry.state, entry.output, entry.error = state, output, error
        entry.output_scale = output_scale
        index = self.index(row)
        self.dataChanged.emit(index, index, list(self._roles))
