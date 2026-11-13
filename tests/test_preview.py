"""Preview geometry follows EXIF orientation independently of visual sizing."""

from pathlib import Path

import pytest
from PIL import Image

from src.ui.preview import ORIENTATION_TAG, image_aspect


@pytest.mark.parametrize('orientation,expected', [(1, 3 / 5), (2, 3 / 5), (6, 5 / 3), (8, 5 / 3)])
def test_preview_uses_oriented_dimensions(
    tmp_path: Path, orientation: int, expected: float
) -> None:
    path = tmp_path / 'oriented.png'
    image = Image.new('RGB', (3, 5))
    exif = image.getexif()
    exif[ORIENTATION_TAG] = orientation
    image.save(path, exif=exif)

    assert image_aspect(path) == pytest.approx(expected)


def test_invalid_preview_has_fallback_geometry(tmp_path: Path) -> None:
    assert image_aspect(None) > 0
    assert image_aspect(tmp_path / 'missing.png') > 0
