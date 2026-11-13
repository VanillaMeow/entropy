"""Isolated native inference process reporting typed events on stdout.

MNN may log to stdout and a faulty GPU driver can crash native code. Keeping it
outside Qt's process preserves UI responsiveness and allows immediate cancel.
"""

from __future__ import annotations

import logging
import sys
import warnings
from functools import partial
from typing import TYPE_CHECKING

from PIL import Image

from src.core.config import UpscaleRequest
from src.core.events import (
    Complete,
    Error,
    ImageError,
    ModelDownload,
    ModelReady,
    Progress,
    RuntimeReady,
    Saved,
    Started,
    Status,
    WorkerEvent,
    encode,
)
from src.core.imaging import load_image, save_output, upscale_image
from src.core.models import ensure_default_model
from src.worker.engine import MnnRunner, gpu_available, import_mnn

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

USAGE = 'Expected --probe, --prepare, or --job with the request JSON on stdin.'


def emit(event: WorkerEvent) -> None:
    """Write one event, starting a fresh line in case MNN left one unfinished."""
    print('\n' + encode(event), flush=True)


def run_batch(request: UpscaleRequest) -> int:
    """Process a batch sequentially and report individual failures honestly."""
    request.output_dir.mkdir(parents=True, exist_ok=True)

    # Downscaling and plain resizing never need the model, so only load it to enlarge
    runner = None
    if request.output_scale > 1:
        model_path = request.model_path or prepare_model()
        if not model_path.is_file() or model_path.suffix.lower() != '.mnn':
            msg = 'The enhancement model is missing. Retry model installation.'
            raise ValueError(msg)

        emit(Status(message='Preparing enhancement…'))
        runner = MnnRunner(str(model_path), request.profile)

    failed = 0
    for index, path in enumerate(request.images):
        emit(Started(index=index, source=path))

        # One bad image must not stop the batch, so it is reported and skipped
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
        except Exception as exc:
            logger.exception('Failed to upscale %s', path)
            failed += 1
            emit(ImageError(index=index, message=str(exc)))
        else:
            emit(
                Saved(
                    index=index,
                    source=path,
                    output=destination,
                    output_scale=request.output_scale,
                )
            )

    emit(Complete(succeeded=len(request.images) - failed, failed=failed))
    return 1 if failed else 0


def prepare_model() -> Path:
    """Install or verify the default model, reporting download progress."""
    path = ensure_default_model(
        progress=lambda done, total: emit(ModelDownload(done=done, total=total))
    )
    emit(ModelReady())

    return path


def probe_runtime() -> None:
    """Load MNN and report whether the platform's GPU backend initializes."""
    mnn = import_mnn()
    emit(RuntimeReady(available=gpu_available(mnn), runtime_path=mnn.__file__))


def _tile_progress(index: int, done: int, total: int) -> None:
    emit(Progress(index=index, done=done, total=total))


def run(arguments: list[str]) -> int:
    """Run one worker mode and return the process exit code."""
    match arguments:
        case ['--probe']:
            probe_runtime()
            return 0

        case ['--prepare']:
            prepare_model()
            probe_runtime()
            return 0

        # The request arrives on stdin, which has no length limit unlike argv
        case ['--job']:
            return run_batch(UpscaleRequest.model_validate_json(sys.stdin.buffer.read()))

        case _:
            raise ValueError(USAGE)


def main() -> int:
    """Run the mode named on the command line, reporting any failure as an event."""
    # Logs go to stderr so stdout carries only events and MNN's own output
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    # Refuse decompression bombs outright instead of only warning about them
    warnings.simplefilter('error', Image.DecompressionBombWarning)

    # This is the process boundary, so the desktop app must hear of every failure
    try:
        return run(sys.argv[1:])
    except Exception as exc:
        logger.exception('Worker failed')
        emit(Error(message=str(exc)))
        return 1
