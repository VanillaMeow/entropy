"""Isolated native inference process with a small JSON event protocol.

MNN may log to stdout and a faulty GPU driver can crash native code. Keeping it
outside Qt's process preserves UI responsiveness and allows immediate cancel.
"""

import json
import logging
import sys
import warnings
from functools import partial
from pathlib import Path
from typing import Any

from PIL import Image

from .config import UpscaleRequest
from .engine import MnnRunner, gpu_available, import_mnn
from .imaging import load_image, save_output, upscale_image
from .models import ensure_default_model

EVENT_PREFIX = "@upscaler@"
logger = logging.getLogger(__name__)


def emit(event: str, **payload: Any) -> None:
    """Flush a protocol message, separating it from native MNN stdout logs."""
    print("\n" + EVENT_PREFIX + json.dumps({"event": event, **payload}), flush=True)


def run_batch(request: UpscaleRequest) -> int:
    """Process a batch sequentially and report individual failures honestly."""
    request.output_dir.mkdir(parents=True, exist_ok=True)
    runner = None
    if request.output_scale > 1:
        model_path = request.model_path or _prepare_model()
        if not model_path.is_file() or model_path.suffix.lower() != ".mnn":
            raise ValueError("The enhancement model is missing. Retry model installation.")
        emit("status", message="Preparing enhancement…")
        runner = MnnRunner(str(model_path), request.profile)
    failed = 0
    for index, path in enumerate(request.images):
        emit("started", index=index, source=str(path))
        try:
            image = load_image(path)
            result = upscale_image(
                image,
                runner,
                scale=request.profile.scale,
                output_scale=request.output_scale,
                tile_size=request.tile_size,
                padding=request.padding,
                progress=partial(_tile_progress, index),
            )
            destination = save_output(
                result, path, request.output_dir, request.output_scale, request.staging_path
            )
            emit(
                "saved",
                index=index,
                source=str(path),
                output=str(destination),
                output_scale=request.output_scale,
            )
        except Exception as exc:
            # This is a process boundary: keep the batch running but mark failures.
            logger.exception("Failed to upscale %s", path)
            failed += 1
            emit("image_error", index=index, message=str(exc))
    emit("complete", succeeded=len(request.images) - failed, failed=failed)
    return 1 if failed else 0


def _tile_progress(index: int, done: int, total: int) -> None:
    emit("progress", index=index, done=done, total=total)


def _prepare_model() -> Path:
    path = ensure_default_model(
        progress=lambda done, total: emit("model_download", done=done, total=total)
    )
    emit("model_ready")
    return path


def main() -> int:
    """Probe the platform's GPU runtime or execute a request from a local JSON file."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    try:
        if sys.argv[1:] in (["--probe"], ["--prepare"]):
            if sys.argv[1] == "--prepare":
                _prepare_model()
            mnn = import_mnn()
            emit(
                "runtime_ready",
                available=gpu_available(mnn),
                runtime_path=mnn.__file__,
            )
            return 0
        if len(sys.argv) != 2:
            raise ValueError("Expected a job JSON path or --probe.")
        request = UpscaleRequest.model_validate_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
        return run_batch(request)
    except Exception as exc:
        logger.exception("Worker failed")
        emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
