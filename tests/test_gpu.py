"""Opt-in real GPU inference with the automatically installed default model."""

import os

import numpy as np
import pytest
from PIL import Image

from src.engine import MnnRunner, gpu_available, import_mnn
from src.imaging import upscale_image
from src.models import DEFAULT_PROFILE, ensure_default_model


@pytest.mark.skipif(
    os.environ.get("UPSCALER_TEST_GPU") != "1", reason="Set UPSCALER_TEST_GPU=1 on a GPU host"
)
@pytest.mark.parametrize("output_scale", [1.5, 2, 3, 4])
def test_default_model_on_gpu(output_scale: float) -> None:
    assert gpu_available(import_mnn()), "The platform's GPU runtime must be available"
    runner = MnnRunner(str(ensure_default_model()), DEFAULT_PROFILE)
    image = Image.new("RGB", (19, 13), (128, 128, 128))
    progress = []
    result = upscale_image(
        image,
        runner,
        scale=4,
        output_scale=output_scale,
        tile_size=16,
        padding=16,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert result.size == (round(19 * output_scale), round(13 * output_scale))
    assert progress[-1] == (2, 2)
    pixels = np.asarray(result)
    # A flat mid-gray image must stay near mid-gray, including edge tiles.
    assert np.abs(pixels.astype(np.float32) - 128).max() < 20
