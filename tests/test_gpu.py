"""Opt-in real GPU inference with the automatically installed default model."""

import os

import numpy as np
import pytest
from PIL import Image

from entropy.core.imaging import upscale_image
from entropy.core.models import DEFAULT_PROFILE, ensure_default_model
from entropy.worker.engine import MnnRunner, gpu_available, import_mnn


@pytest.mark.skipif(
    os.environ.get('ENTROPY_TEST_GPU') != '1', reason='Set ENTROPY_TEST_GPU=1 on a GPU host'
)
@pytest.mark.parametrize('output_scale', [1.5, 2, 3, 4])
def test_default_model_on_gpu(output_scale: float) -> None:
    assert gpu_available(import_mnn()), "The platform's GPU runtime must be available"
    runner = MnnRunner(str(ensure_default_model()), DEFAULT_PROFILE)

    image = Image.new('RGB', (19, 13), (128, 128, 128))
    progress: list[tuple[int, int]] = []

    result = upscale_image(
        image,
        runner,
        scale=4,
        output_scale=output_scale,
        tile_size=16,
        padding=16,
        progress=lambda done, total: progress.append((done, total)),
    )

    # 19x13 in 16px tiles is two tiles wide and one tall
    assert result.size == (round(19 * output_scale), round(13 * output_scale))
    assert progress[-1] == (2, 2)

    # A flat mid-gray image must stay near mid-gray, including edge tiles
    pixels = np.asarray(result)
    assert np.abs(pixels.astype(np.float32) - 128).max() < 20
