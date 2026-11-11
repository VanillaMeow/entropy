"""Model contracts are validated before native inference starts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.config import ModelProfile, UpscaleRequest


@pytest.mark.parametrize(
    "payload",
    [{"scale": 1}, {"layout": "BGR"}, {"input_name": "input"}, {"scsale": 4}],
)
def test_invalid_profile_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ModelProfile.model_validate(payload)


def test_request_round_trip(tmp_path: Path) -> None:
    request = UpscaleRequest(
        images=(tmp_path / "a.png",), model_path=tmp_path / "model.mnn", output_dir=tmp_path
    )
    assert UpscaleRequest.model_validate_json(request.model_dump_json()) == request
    assert request.staging_path.parent == tmp_path


@pytest.mark.parametrize("backend", ["CPU", "Vulkan", "OpenCL", "Metal"])
def test_request_rejects_backend_selection(tmp_path: Path, backend: str) -> None:
    with pytest.raises(ValidationError):
        UpscaleRequest.model_validate(
            {"images": [tmp_path / "a.png"], "output_dir": tmp_path, "backend": backend}
        )


@pytest.mark.parametrize("scale", [0, -1, 0.09, 4.01, float("nan"), float("inf")])
def test_invalid_output_scale_is_rejected(tmp_path: Path, scale: float) -> None:
    with pytest.raises(ValidationError):
        UpscaleRequest(images=(tmp_path / "a.png",), output_dir=tmp_path, output_scale=scale)
