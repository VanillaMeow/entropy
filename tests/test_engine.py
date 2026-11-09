"""Exercise the native Module API on CPU and GPU availability errors separately."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from src import engine
from src.config import ModelProfile
from src.engine import InferenceError, MnnRunner


@pytest.mark.parametrize("compiled", [False, True])
def test_unavailable_gpu_is_rejected(monkeypatch: pytest.MonkeyPatch, compiled: bool) -> None:
    fake = SimpleNamespace(
        Interpreter=SimpleNamespace(createRuntime=lambda _: (object(), (False,)))
    )
    monkeypatch.setattr(engine, "import_mnn", lambda: fake)
    monkeypatch.setattr(engine, "is_compiled", lambda: compiled)
    with pytest.raises(InferenceError, match="OpenCL could not initialize") as error:
        MnnRunner("unused.mnn", ModelProfile())
    if compiled:
        assert "driver" in str(error.value)
        assert "uv run" not in str(error.value)


@pytest.fixture
def native_cpu(monkeypatch: pytest.MonkeyPatch) -> Any:
    # No CPU backend is exposed in the app. Map the test backend to CPU solely
    # to exercise real model IO on CI machines lacking GPU-enabled MNN builds.
    try:
        engine.import_mnn()
    except InferenceError as exc:
        pytest.skip(str(exc))
    import MNN.expr as expr

    monkeypatch.setattr(engine, "OPENCL_BACKEND", 0)
    return expr


def make_resize_model(expr: Any, path: Path, layout: str, *, packed: bool = False) -> None:
    shape = [1, 3, 4, 5] if layout == "NCHW" else [1, 4, 5, 3]
    order = expr.NCHW if layout == "NCHW" else expr.NHWC
    source = expr.placeholder(shape, expr.NC4HW4 if packed else order)
    source.name = "input"
    output = expr.convert(expr.resize(expr.convert(source, expr.NC4HW4), 2.0, 2.0), order)
    output.name = "output"
    expr.save([output], str(path))


@pytest.mark.parametrize("layout,packed", [("NCHW", False), ("NHWC", False), ("NCHW", True)])
def test_native_dynamic_model_preserves_channels_and_scale(
    native_cpu: Any, tmp_path: Path, layout: str, packed: bool
) -> None:
    path = tmp_path / "resize.mnn"
    make_resize_model(native_cpu, path, layout, packed=packed)
    runner = MnnRunner(str(path), ModelProfile(scale=2, layout=layout))
    for height, width in [(6, 7), (9, 3), (1, 1)]:
        pixels = np.full((height, width, 3), [0.1, 0.4, 0.9], dtype=np.float32)
        output = runner.infer(pixels)
        assert output.shape == (height * 2, width * 2, 3)
        np.testing.assert_allclose(
            output, np.broadcast_to([0.1, 0.4, 0.9], output.shape), atol=1e-6
        )


def test_native_scale_mismatch_is_rejected(native_cpu: Any, tmp_path: Path) -> None:
    path = tmp_path / "resize.mnn"
    make_resize_model(native_cpu, path, "NCHW")
    runner = MnnRunner(str(path), ModelProfile(scale=4))
    with pytest.raises(InferenceError, match="Check the model scale"):
        runner.infer(np.ones((4, 5, 3), dtype=np.float32))
