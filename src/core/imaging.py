"""Image loading, padded tiling, and collision-safe PNG output."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

SUPPORTED_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'})

type FloatImage = NDArray[np.float32]


class TileRunner(Protocol):
    """Small interface for normalized HWC RGB tile inference."""

    def infer(self, pixels: FloatImage) -> FloatImage:
        """Upscale a tile with values in [0, 1], returning HWC RGB pixels."""
        ...


def upscale_image(
    image: Image.Image,
    runner: TileRunner | None,
    *,
    scale: int,
    tile_size: int,
    padding: int,
    progress: Callable[[int, int], None],
    output_scale: float | None = None,
) -> Image.Image:
    """Enhance padded tiles and resize to the requested output scale.

    Input is EXIF-oriented before this function. Alpha is resized separately;
    inference always sees normalized RGB. Output is an 8-bit RGB/RGBA image.
    Scales at or below 1 bypass inference. Dimensions round to the nearest
    pixel with a minimum of one pixel per side. Omit output_scale to retain
    the model's native scale.
    Tile padding reduces seams but cannot guarantee equivalence to full-frame
    inference for models with large receptive fields or global operations.
    """
    final_scale = scale if output_scale is None else output_scale
    if final_scale <= 1:
        output = image.convert('RGB')
        output.info.clear()
        progress(1, 1)
    else:
        if runner is None:
            msg = 'An enhancement model is required for upscaling.'
            raise ValueError(msg)
        output = _upscale_rgb(
            image, runner, scale=scale, tile_size=tile_size, padding=padding, progress=progress
        )
    width, height = image.size
    size = (max(1, round(width * final_scale)), max(1, round(height * final_scale)))
    if output.size != size:
        output = output.resize(size, Image.Resampling.LANCZOS)
    if image.has_transparency_data:
        alpha = image.convert('RGBA').getchannel('A')
        output.putalpha(alpha.resize(output.size, Image.Resampling.LANCZOS))
    # Non-RGB profiles (for example CMYK JPEG) cannot tag an RGB PNG unchanged.
    if image.mode in {'RGB', 'RGBA', 'P'} and 'icc_profile' in image.info:
        output.info['icc_profile'] = image.info['icc_profile']
    return output


def _upscale_rgb(
    image: Image.Image,
    runner: TileRunner,
    *,
    scale: int,
    tile_size: int,
    padding: int,
    progress: Callable[[int, int], None],
) -> Image.Image:
    width, height = image.size
    output = Image.new('RGB', (width * scale, height * scale))
    total = ((width + tile_size - 1) // tile_size) * ((height + tile_size - 1) // tile_size)
    completed = 0
    rgb = image.convert('RGB')
    for top in range(0, height, tile_size):
        for left in range(0, width, tile_size):
            right, bottom = min(left + tile_size, width), min(top + tile_size, height)
            x0, y0 = max(0, left - padding), max(0, top - padding)
            x1, y1 = min(width, right + padding), min(height, bottom + padding)
            pixels = np.asarray(rgb.crop((x0, y0, x1, y1)), dtype=np.float32) / 255.0
            result = runner.infer(pixels)
            expected = ((y1 - y0) * scale, (x1 - x0) * scale, 3)
            if result.shape != expected or not np.isfinite(result).all():
                msg = f'Invalid tile output: expected finite RGB pixels with shape {expected}.'
                raise ValueError(msg)
            crop = result[
                (top - y0) * scale : (bottom - y0) * scale,
                (left - x0) * scale : (right - x0) * scale,
            ]
            tile = Image.fromarray(np.rint(np.clip(crop, 0, 1) * 255).astype(np.uint8))
            output.paste(tile, (left * scale, top * scale))
            completed += 1
            progress(completed, total)
    return output


def load_image(path: Path) -> Image.Image:
    """Load a static image, honoring orientation and retaining its color profile."""
    with Image.open(path) as source:
        if getattr(source, 'n_frames', 1) != 1:
            msg = 'Animated and multipage images are not supported yet.'
            raise ValueError(msg)
        oriented = ImageOps.exif_transpose(source)
        oriented.load()
        return oriented.copy()


def save_output(
    image: Image.Image, source: Path, output_dir: Path, scale: float, staging_path: Path
) -> Path:
    """Publish a complete PNG using an exclusive hard link; never overwrite a file.

    Scratch and destination share a directory, making publication atomic. The
    parent UI owns the scratch filename and also removes it after cancellation.
    """
    created = False
    try:
        with staging_path.open('xb') as stream:
            created = True
            image.save(stream, format='PNG', icc_profile=image.info.get('icc_profile'))
        stem = f'{source.stem}_{scale:g}x'
        number = 0
        while True:
            suffix = f'_{number}' if number else ''
            destination = output_dir / f'{stem}{suffix}.png'
            try:
                destination.hardlink_to(staging_path)
            except FileExistsError:
                number += 1
                continue
            return destination
    finally:
        if created:
            staging_path.unlink(missing_ok=True)
