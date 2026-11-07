"""GPU model execution, kept independent of Qt and image file handling."""

from importlib import import_module
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from .config import Backend, ModelProfile
from .runtime import activate_local_runtime

FloatImage = NDArray[np.float32]


class InferenceError(RuntimeError):
    """Model execution or GPU initialization failed."""


class TileRunner(Protocol):
    """Small interface for normalized HWC RGB tile inference."""

    def infer(self, pixels: FloatImage) -> FloatImage:
        """Upscale a tile with values in [0, 1], returning HWC RGB pixels."""
        ...


def import_mnn() -> Any:
    """Load the optional native runtime with an actionable installation error."""
    try:
        activate_local_runtime()
        return import_module("MNN")
    except ImportError as exc:
        raise InferenceError(
            "MNN could not be loaded. Run 'uv run python scripts/build_mnn.py' "
            "to install the GPU runtime. "
            f"Native loader error: {exc}"
        ) from exc


def available_backends(mnn: Any) -> dict[Backend, bool]:
    """Probe runtime creation, including driver availability.

    MNN.nn does not expose a capability query. The legacy Interpreter static
    method is used only for this check; inference uses the maintained nn API.
    """
    return {backend: _backend_available(mnn, backend) for backend in Backend}


def _backend_available(mnn: Any, backend: Backend) -> bool:
    runtime, supported = mnn.Interpreter.createRuntime(({"backend": backend.mnn_id},))
    available = bool(supported[0])
    del runtime
    return available


class MnnRunner:
    """Run a dynamic RGB model with MNN's Module/RuntimeManager API."""

    def __init__(self, model_path: str, profile: ModelProfile, backend: Backend) -> None:
        self._mnn = import_mnn()
        if not _backend_available(self._mnn, backend):
            raise InferenceError(
                f"{backend.value} could not initialize. The standard MNN wheel omits GPU backends. "
                "Run 'uv run python scripts/build_mnn.py' to build a GPU runtime. "
                "If already built, check the GPU driver and runtime diagnostics."
            )
        self._expr = import_module("MNN.expr")
        nn = import_module("MNN.nn")
        self._profile = profile
        self._runtime = nn.create_runtime_manager(
            ({"backend": backend.mnn_id, "precision": "high", "numThread": 4},)
        )
        # Fix the requested primary backend; MNN may still run unsupported ops on CPU.
        self._runtime.set_mode(8)
        self._module = nn.load_module_from_file(
            model_path,
            [profile.input_name] if profile.input_name else [],
            [profile.output_name] if profile.output_name else [],
            runtime_manager=self._runtime,
            shape_mutable=True,
        )
        info = self._module.get_info()
        graph = self._expr.load_as_dict(model_path)
        inputs, _ = self._expr.get_inputs_and_outputs(graph)
        input_names, output_names = info["inputNames"], info["outputNames"]
        if len(input_names) != 1 or len(output_names) != 1 or len(inputs) != 1:
            raise InferenceError("Select a model with exactly one image input and output.")
        if input_names[0] not in inputs or output_names[0] not in graph:
            raise InferenceError(
                "The tensor names in the model profile were not found in the model."
            )
        source = inputs[input_names[0]]
        self._input_format = source.data_format
        channel_axis = 1 if profile.layout == "NCHW" else 3
        if len(source.shape) != 4 or source.shape[channel_axis] != 3:
            raise InferenceError("The model must accept a batch of three-channel RGB images.")
        if source.dtype != self._expr.float:
            raise InferenceError("The model must accept float32 pixels normalized to 0–1.")

    def infer(self, pixels: FloatImage) -> FloatImage:
        """Execute one tile and validate its spatial scale and pixel values."""
        expr = self._expr
        if self._profile.layout == "NCHW":
            data = np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])
            order = expr.NCHW
        else:
            data = np.ascontiguousarray(pixels[None])
            order = expr.NHWC
        value = expr.const(data, list(data.shape), order, expr.float)
        value = expr.convert(value, self._input_format)
        output = self._module.forward(value)
        result = np.asarray(expr.convert(output, expr.NHWC).read(), dtype=np.float32)
        height, width = pixels.shape[:2]
        expected = (1, height * self._profile.scale, width * self._profile.scale, 3)
        if result.shape != expected:
            raise InferenceError(
                f"Model returned {result.shape}; expected {expected}. "
                "Check the model scale and layout in its JSON profile."
            )
        if not np.isfinite(result).all():
            raise InferenceError("Model returned non-finite pixels; try another model or backend.")
        return np.clip(result[0], 0, 1)
