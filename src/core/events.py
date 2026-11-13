"""Typed messages from the inference worker to the desktop process.

The worker writes one JSON event per line to stdout. MNN prints its own native
logs to the same stream, so each event line starts with ``EVENT_PREFIX`` and
the desktop process treats every other line as diagnostic output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

EVENT_PREFIX = '@entropy@'


class _Event(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class ModelDownload(_Event):
    """Progress of the one-time default model download, in bytes."""

    event: Literal['model_download'] = 'model_download'
    done: int
    total: int


class ModelReady(_Event):
    """The default model is installed and verified."""

    event: Literal['model_ready'] = 'model_ready'


class RuntimeReady(_Event):
    """Result of probing the GPU runtime."""

    event: Literal['runtime_ready'] = 'runtime_ready'
    available: bool
    runtime_path: str | None = None


class Status(_Event):
    """A user-facing status message."""

    event: Literal['status'] = 'status'
    message: str


class Started(_Event):
    """Processing of one queued image has begun."""

    event: Literal['started'] = 'started'
    index: int
    source: Path


class Progress(_Event):
    """Tile progress within one image."""

    event: Literal['progress'] = 'progress'
    index: int
    done: int
    total: int


class Saved(_Event):
    """One image was written to the output folder."""

    event: Literal['saved'] = 'saved'
    index: int
    source: Path
    output: Path
    output_scale: float


class ImageError(_Event):
    """One image failed; the rest of the batch continues."""

    event: Literal['image_error'] = 'image_error'
    index: int
    message: str


class Error(_Event):
    """The worker failed as a whole."""

    event: Literal['error'] = 'error'
    message: str


class Complete(_Event):
    """The batch finished."""

    event: Literal['complete'] = 'complete'
    succeeded: int
    failed: int


type WorkerEvent = Annotated[
    ModelDownload
    | ModelReady
    | RuntimeReady
    | Status
    | Started
    | Progress
    | Saved
    | ImageError
    | Error
    | Complete,
    Field(discriminator='event'),
]

_ADAPTER: TypeAdapter[WorkerEvent] = TypeAdapter(WorkerEvent)


def encode(event: WorkerEvent) -> str:
    """Serialize an event as one protocol line, without the trailing newline."""
    return EVENT_PREFIX + event.model_dump_json()


def decode(line: str) -> WorkerEvent | None:
    """Parse a protocol line, or return None for ordinary log output.

    Raises ``pydantic.ValidationError`` for a line that carries the prefix but
    is not a valid event.
    """
    if not line.startswith(EVENT_PREFIX):
        return None
    return _ADAPTER.validate_json(line.removeprefix(EVENT_PREFIX))
