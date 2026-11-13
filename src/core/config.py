"""Validated settings shared by the desktop UI and inference process."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelProfile(BaseModel):
    """Contract for a single-input RGB super-resolution model.

    Tensor names are discovered from the model when both names are omitted.
    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    scale: int = Field(default=4, ge=2, le=8)
    layout: Literal['NCHW', 'NHWC'] = 'NCHW'
    input_name: str | None = Field(default=None, min_length=1)
    output_name: str | None = Field(default=None, min_length=1)

    @model_validator(mode='after')
    def paired_names(self) -> Self:
        """Require either two explicit tensor names or automatic discovery."""
        if (self.input_name is None) != (self.output_name is None):
            msg = 'Specify both input_name and output_name, or omit both.'
            raise ValueError(msg)
        return self


class UpscaleRequest(BaseModel):
    """Immutable batch request crossing the subprocess boundary."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    images: tuple[Path, ...] = Field(min_length=1)
    model_path: Path | None = None
    output_dir: Path
    profile: ModelProfile = Field(default_factory=ModelProfile)
    output_scale: float = Field(default=4.0, ge=0.1, le=4.0, allow_inf_nan=False)
    tile_size: int = Field(default=128, ge=16, le=1024)
    padding: int = Field(default=16, ge=0, le=128)
    job_id: UUID = Field(default_factory=uuid4)

    @property
    def staging_path(self) -> Path:
        """Return the single scratch output owned by this batch."""
        return self.output_dir / f'.entropy-{self.job_id}.tmp'
