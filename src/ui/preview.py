"""Bounded, EXIF-oriented previews decoded by Qt Quick's image worker thread."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, override

from PIL import Image, ImageOps
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from src.logic.image_queue import preview_path

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtCore import QSize

logger = logging.getLogger(__name__)

# EXIF orientations that swap width and height
TRANSPOSED = frozenset({5, 6, 7, 8})
ORIENTATION_TAG = 274

# Caps decoding cost even if QML asks for a huge preview
MAX_PREVIEW_EDGE = 2048

# A typical photo shape, used while the real geometry is unknown
FALLBACK_ASPECT = 1.5


def image_aspect(path: Path | None) -> float:
    """Read header geometry with the EXIF rotation used by inference."""
    if path is None:
        return FALLBACK_ASPECT

    try:
        with Image.open(path) as image:
            width, height = image.size

            # Untagged PNG getexif() can trigger a full decode, so skip it there
            orientation = (
                image.getexif().get(ORIENTATION_TAG, 1)
                if image.format != 'PNG' or 'exif' in image.info
                else 1
            )

            return height / width if orientation in TRANSPOSED else width / height
    except (OSError, ValueError) as exc:
        logger.warning('Could not read preview geometry for %s: %s', path, exc)
        return FALLBACK_ASPECT


class PreviewProvider(QQuickImageProvider):
    """Load oriented thumbnails asynchronously, including PNG EXIF support."""

    def __init__(self) -> None:
        super().__init__(self.ImageType.Image, self.Flag.ForceAsynchronousImageLoading)

    @override
    def requestImage(self, token: str, size: QSize, requestedSize: QSize) -> QImage:
        # An empty image shows the delegate's placeholder instead of breaking the list
        try:
            result = load_thumbnail(preview_path(token), requestedSize)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            logger.warning('Could not load image preview: %s', exc)
            return QImage()

        # Qt reads the real size back through this out-parameter
        size.setWidth(result.width())
        size.setHeight(result.height())

        return result


def load_thumbnail(path: Path, requested: QSize) -> QImage:
    """Decode an upright thumbnail no larger than the requested size."""
    with Image.open(path) as source:
        orientation = source.getexif().get(ORIENTATION_TAG, 1)
        width = min(MAX_PREVIEW_EDGE, max(1, requested.width()))
        height = min(MAX_PREVIEW_EDGE, max(1, requested.height()))

        # Thumbnail before rotating, so swap the box for sideways orientations
        source.thumbnail((height, width) if orientation in TRANSPOSED else (width, height))
        image = ImageOps.exif_transpose(source).convert('RGBA')

        # Copy so the QImage owns its pixels once the Python bytes are gone
        return QImage(
            image.tobytes(), image.width, image.height, QImage.Format.Format_RGBA8888
        ).copy()
