"""Opt-in real GPU inference with the automatically installed default model."""

import os

import numpy as np
import pytest
from PIL import Image

from placeholder_upscaler.config import Backend
from placeholder_upscaler.engine import MnnRunner, available_backends, import_mnn
from placeholder_upscaler.imaging import upscale_image
from placeholder_upscaler.models import DEFAULT_PROFILE, ensure_default_model


@pytest.mark.skipif(
    os.environ.get("UPSCALER_TEST_GPU") != "1", reason="Set UPSCALER_TEST_GPU=1 on a GPU host"
)
@pytest.mark.parametrize("backend", list(Backend))
def test_default_model_on_gpu(backend: Backend) -> None:
    assert available_backends(import_mnn())[backend], f"{backend.value} must be available"
    runner = MnnRunner(str(ensure_default_model()), DEFAULT_PROFILE, backend)
    image = Image.new("RGB", (19, 13), (128, 128, 128))
    progress = []
    result = upscale_image(
        image,
        runner,
        scale=4,
        tile_size=16,
        padding=16,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert result.size == (76, 52)
    assert progress[-1] == (2, 2)
    pixels = np.asarray(result)
    # A flat mid-gray image must stay near mid-gray, including edge tiles.
    assert np.abs(pixels.astype(np.float32) - 128).max() < 20
