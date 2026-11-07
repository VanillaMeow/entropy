"""Model contracts are validated before native inference starts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Backend, ModelProfile, UpscaleRequest


@pytest.mark.parametrize(
    "payload",
    [{"scale": 1}, {"layout": "BGR"}, {"input_name": "input"}, {"scsale": 4}],
)
def test_invalid_profile_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ModelProfile.model_validate(payload)


def test_request_round_trip_and_gpu_only_contract(tmp_path: Path) -> None:
    request = UpscaleRequest(
        images=(tmp_path / "a.png",), model_path=tmp_path / "model.mnn", output_dir=tmp_path
    )
    assert UpscaleRequest.model_validate_json(request.model_dump_json()) == request
    assert request.staging_path.parent == tmp_path
    assert Backend.OPENCL.mnn_id == 3
    assert Backend.VULKAN.mnn_id == 7
    with pytest.raises(ValidationError):
        UpscaleRequest.model_validate({**request.model_dump(), "backend": "CPU"})


@pytest.mark.parametrize("scale", [0, -1, 0.09, 4.01, float("nan"), float("inf")])
def test_invalid_output_scale_is_rejected(tmp_path: Path, scale: float) -> None:
    with pytest.raises(ValidationError):
        UpscaleRequest(images=(tmp_path / "a.png",), output_dir=tmp_path, output_scale=scale)
