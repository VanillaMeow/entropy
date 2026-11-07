"""Check tile boundaries, transparency, orientation and non-destructive output."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from placeholder_upscaler.engine import FloatImage
from placeholder_upscaler.imaging import load_image, save_output, upscale_image


class NearestRunner:
    def infer(self, pixels: FloatImage) -> FloatImage:
        return pixels.repeat(2, axis=0).repeat(2, axis=1)


@pytest.mark.parametrize("size", [(1, 1), (17, 13), (32, 32), (35, 49)])
@pytest.mark.parametrize("padding", [0, 4, 32])
def test_tiles_cover_every_pixel_without_seams(size: tuple[int, int], padding: int) -> None:
    width, height = size
    pixels = np.random.default_rng(42).integers(0, 256, (height, width, 3), dtype=np.uint8)
    progress = []
    result = upscale_image(
        Image.fromarray(pixels),
        NearestRunner(),
        scale=2,
        tile_size=16,
        padding=padding,
        progress=lambda done, total: progress.append((done, total)),
    )
    np.testing.assert_array_equal(np.asarray(result), pixels.repeat(2, 0).repeat(2, 1))
    count = ((width + 15) // 16) * ((height + 15) // 16)
    assert progress == [(i, count) for i in range(1, count + 1)]


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_alpha_is_preserved(mode: str) -> None:
    rgba = Image.new("RGBA", (5, 7), (100, 150, 200, 80))
    image = rgba.convert(mode)
    result = upscale_image(
        image, NearestRunner(), scale=2, tile_size=16, padding=4, progress=lambda *_: None
    )
    expected = image.convert("RGBA").getchannel("A").resize(result.size, Image.Resampling.LANCZOS)
    assert result.mode == "RGBA"
    np.testing.assert_array_equal(np.asarray(result.getchannel("A")), np.asarray(expected))


@pytest.mark.parametrize("output_scale", [0.1, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4])
@pytest.mark.parametrize("mode", ["RGB", "RGBA", "LA", "P", "CMYK"])
def test_custom_output_sizes_and_metadata(output_scale: float, mode: str) -> None:
    image = Image.new("RGBA", (19, 11), (100, 150, 200, 80)).convert(mode)
    if mode == "P":
        image.info["transparency"] = 0
    image.info["icc_profile"] = b"test profile"
    result = upscale_image(
        image,
        NearestRunner() if output_scale > 1 else None,
        scale=2,
        output_scale=output_scale,
        tile_size=16,
        padding=4,
        progress=lambda *_: None,
    )
    assert result.size == (max(1, round(19 * output_scale)), max(1, round(11 * output_scale)))
    assert result.info.get("icc_profile") == (
        b"test profile" if mode in {"RGB", "RGBA", "P"} else None
    )
    if image.has_transparency_data:
        expected = (
            image.convert("RGBA").getchannel("A").resize(result.size, Image.Resampling.LANCZOS)
        )
        assert result.mode == "RGBA"
        np.testing.assert_array_equal(result.getchannel("A"), expected)
    else:
        assert result.mode == "RGB"


def test_tiny_downscale_stays_at_least_one_pixel() -> None:
    result = upscale_image(
        Image.new("RGB", (1, 2)),
        None,
        scale=4,
        output_scale=0.1,
        tile_size=16,
        padding=0,
        progress=lambda *_: None,
    )
    assert result.size == (1, 1)


def test_loading_applies_exif_orientation(tmp_path: Path) -> None:
    path = tmp_path / "rotated.png"
    image = Image.new("RGB", (3, 5))
    exif = image.getexif()
    exif[274] = 6
    image.save(path, exif=exif)
    result = load_image(path)
    assert result.size == (5, 3)
    assert result.getexif().get(274) is None


def test_multipage_input_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "animation.webp"
    Image.new("RGB", (2, 2), "red").save(
        path, save_all=True, append_images=[Image.new("RGB", (2, 2), "blue")], duration=100
    )
    with pytest.raises(ValueError, match="Animated and multipage"):
        load_image(path)


def test_publication_never_overwrites_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"original")
    existing = tmp_path / "source_2x.png"
    existing.write_bytes(b"existing")
    stage = tmp_path / ".stage.tmp"
    image = Image.new("RGB", (4, 6), "red")
    result = save_output(image, source, tmp_path, 2, stage)
    assert result.name == "source_2x_1.png"
    assert source.read_bytes() == b"original"
    assert existing.read_bytes() == b"existing"
    assert not stage.exists()
    with Image.open(result) as saved:
        assert saved.size == image.size
        assert saved.getpixel((0, 0)) == (255, 0, 0)


def test_unowned_staging_file_is_not_deleted(tmp_path: Path) -> None:
    stage = tmp_path / ".stage.tmp"
    stage.write_bytes(b"owned by someone else")
    with pytest.raises(FileExistsError):
        save_output(Image.new("RGB", (2, 2)), tmp_path / "a.png", tmp_path, 2, stage)
    assert stage.read_bytes() == b"owned by someone else"


@pytest.mark.parametrize("bad_shape", [True, False])
def test_invalid_tensor_output_is_rejected(bad_shape: bool) -> None:
    class BrokenRunner:
        def infer(self, pixels: FloatImage) -> FloatImage:
            if bad_shape:
                return pixels
            return np.full((4, 4, 3), np.nan, dtype=np.float32)

    with pytest.raises(ValueError, match="Invalid tile output"):
        upscale_image(
            Image.new("RGB", (2, 2)),
            BrokenRunner(),
            scale=2,
            tile_size=16,
            padding=0,
            progress=lambda *_: None,
        )
