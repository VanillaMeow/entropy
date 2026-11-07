"""Bounded, EXIF-oriented previews decoded by Qt Quick's image worker thread."""

import base64
import logging
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QSize, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

logger = logging.getLogger(__name__)


def image_aspect(path: Path | None) -> float:
    """Read header geometry with the EXIF rotation used by inference."""
    if path is None:
        return 1.5
    try:
        with Image.open(path) as image:
            width, height = image.size
            # Untagged PNG getexif() can trigger a full decode; avoid that here.
            orientation = (
                image.getexif().get(274, 1) if image.format != "PNG" or "exif" in image.info else 1
            )
            return height / width if orientation in {5, 6, 7, 8} else width / height
    except (OSError, ValueError) as exc:
        logger.warning("Could not read preview geometry for %s: %s", path, exc)
        return 1.5


def preview_url(path: Path | None) -> QUrl:
    """Encode a local path as an unambiguous image-provider URL."""
    if path is None:
        return QUrl()
    token = base64.urlsafe_b64encode(str(path).encode("utf-8")).decode("ascii")
    return QUrl("image://preview/" + token)


class PreviewProvider(QQuickImageProvider):
    """Load oriented thumbnails asynchronously, including PNG EXIF support."""

    def __init__(self) -> None:
        super().__init__(self.ImageType.Image, self.Flag.ForceAsynchronousImageLoading)

    def requestImage(self, identifier: str, size: QSize, requestedSize: QSize) -> QImage:
        try:
            path = Path(base64.urlsafe_b64decode(identifier).decode("utf-8"))
            with Image.open(path) as source:
                orientation = source.getexif().get(274, 1)
                box = (
                    min(2048, max(1, requestedSize.width())),
                    min(2048, max(1, requestedSize.height())),
                )
                source.thumbnail(box[::-1] if orientation in {5, 6, 7, 8} else box)
                image = ImageOps.exif_transpose(source).convert("RGBA")
                result = QImage(
                    image.tobytes(), image.width, image.height, QImage.Format.Format_RGBA8888
                ).copy()
            size.setWidth(result.width())
            size.setHeight(result.height())
            return result
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            logger.warning("Could not load image preview: %s", exc)
            return QImage()
