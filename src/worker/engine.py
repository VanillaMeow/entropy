"""GPU model execution, kept independent of Qt and image file handling."""

from __future__ import annotations

import sys
from importlib import import_module
from typing import TYPE_CHECKING, Any

import numpy as np

from src.paths import is_compiled
from src.worker.runtime import activate_local_runtime

if TYPE_CHECKING:
    from src.core.config import ModelProfile
    from src.core.imaging import FloatImage

# MNN's session mode that keeps the chosen backend primary instead of falling back to CPU
BACKEND_PRIMARY_MODE = 8


class InferenceError(RuntimeError):
    """Model execution or GPU initialization failed."""


def import_mnn() -> Any:
    """Load the optional native runtime with an actionable installation error."""
    try:
        activate_local_runtime()
        return import_module('MNN')
    except ImportError as exc:
        raise InferenceError(_import_error_message(exc)) from exc


def _import_error_message(exc: ImportError) -> str:
    """Explain how to get a working runtime on this kind of install."""
    if is_compiled():
        return (
            'The bundled GPU runtime could not be loaded. Reinstall Entropy and '
            f'check the GPU driver. Native loader error: {exc}'
        )

    if sys.platform == 'darwin':
        return (
            'MNN could not be loaded. Install a macOS MNN runtime with Metal support. '
            f'Native loader error: {exc}'
        )

    return (
        "MNN could not be loaded. Run 'uv run python scripts/build_mnn.py' "
        'to install the GPU runtime. '
        f'Native loader error: {exc}'
    )


def gpu_backend() -> tuple[str, int]:
    """Select Metal on macOS and OpenCL elsewhere, without a user setting."""
    return ('Metal', 1) if sys.platform == 'darwin' else ('OpenCL', 3)


def gpu_available(mnn: Any) -> bool:
    """Probe runtime creation, including driver availability.

    MNN.nn does not expose a capability query. The legacy Interpreter static
    method is used only for this check; inference uses the maintained nn API.
    """
    _, backend_id = gpu_backend()
    runtime, supported = mnn.Interpreter.createRuntime(({'backend': backend_id},))
    available = bool(supported[0])

    # Release the probe runtime right away, it holds a GPU context
    del runtime

    return available


def _unavailable_message(backend_name: str) -> str:
    """Explain why the GPU backend failed to start on this kind of install."""
    if is_compiled():
        return (
            f'{backend_name} could not initialize. Check that a compatible GPU '
            'driver is installed, then retry setup.'
        )

    if sys.platform == 'darwin':
        return (
            'Metal could not initialize. A Metal-capable Mac and an MNN runtime '
            'built with Metal support are required.'
        )

    return (
        'OpenCL could not initialize. The standard MNN wheel omits OpenCL support. '
        "Run 'uv run python scripts/build_mnn.py' to build a GPU runtime. "
        'If already built, check the GPU driver and runtime diagnostics.'
    )


class MnnRunner:
    """Run a dynamic RGB model with MNN's Module/RuntimeManager API."""

    def __init__(self, model_path: str, profile: ModelProfile) -> None:
        backend_name, backend_id = gpu_backend()

        # Fail early with a useful message, MNN's own errors only say the backend is missing
        self._mnn = import_mnn()
        if not gpu_available(self._mnn):
            raise InferenceError(_unavailable_message(backend_name))

        self._expr = import_module('MNN.expr')
        self._profile = profile

        nn = import_module('MNN.nn')
        self._runtime = nn.create_runtime_manager(
            ({'backend': backend_id, 'precision': 'high', 'numThread': 4},)
        )
        self._runtime.set_mode(BACKEND_PRIMARY_MODE)

        # Empty name lists let MNN discover the model's single input and output
        self._module = nn.load_module_from_file(
            model_path,
            [profile.input_name] if profile.input_name else [],
            [profile.output_name] if profile.output_name else [],
            runtime_manager=self._runtime,
            shape_mutable=True,
        )
        self._input_format = self._validate_model(model_path)

    def _validate_model(self, model_path: str) -> Any:
        """Check the model takes one float RGB batch, and return its input format."""
        info = self._module.get_info()
        graph = self._expr.load_as_dict(model_path)
        inputs, _ = self._expr.get_inputs_and_outputs(graph)

        input_names, output_names = info['inputNames'], info['outputNames']
        if len(input_names) != 1 or len(output_names) != 1 or len(inputs) != 1:
            msg = 'Select a model with exactly one image input and output.'
            raise InferenceError(msg)

        if input_names[0] not in inputs or output_names[0] not in graph:
            msg = 'The tensor names in the model profile were not found in the model.'
            raise InferenceError(msg)

        source = inputs[input_names[0]]
        channel_axis = 1 if self._profile.layout == 'NCHW' else 3
        if len(source.shape) != 4 or source.shape[channel_axis] != 3:
            msg = 'The model must accept a batch of three-channel RGB images.'
            raise InferenceError(msg)

        if source.dtype != self._expr.float:
            msg = 'The model must accept float32 pixels normalized to 0–1.'
            raise InferenceError(msg)

        return source.data_format

    def infer(self, pixels: FloatImage) -> FloatImage:
        """Execute one tile and validate its spatial scale and pixel values."""
        expr = self._expr

        # Add the batch axis, and move channels first for NCHW models
        if self._profile.layout == 'NCHW':
            data = np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])
            order = expr.NCHW
        else:
            data = np.ascontiguousarray(pixels[None])
            order = expr.NHWC

        value = expr.const(data, list(data.shape), order, expr.float)
        value = expr.convert(value, self._input_format)
        output = self._module.forward(value)
        result = np.asarray(expr.convert(output, expr.NHWC).read(), dtype=np.float32)

        # A wrong profile shows up here as a shape mismatch, not as garbage pixels
        height, width = pixels.shape[:2]
        expected = (1, height * self._profile.scale, width * self._profile.scale, 3)
        if result.shape != expected:
            msg = (
                f'Model returned {result.shape}; expected {expected}. '
                'Check the model scale and layout in its JSON profile.'
            )
            raise InferenceError(msg)

        if not np.isfinite(result).all():
            msg = 'Model returned non-finite pixels; check the model and GPU driver.'
            raise InferenceError(msg)

        return np.clip(result[0], 0, 1)
