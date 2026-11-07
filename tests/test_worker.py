"""A failed image must not hide successful work or stop the remaining batch."""

import json
from pathlib import Path

import pytest
from PIL import Image

from placeholder_upscaler import worker
from placeholder_upscaler.config import ModelProfile, UpscaleRequest
from placeholder_upscaler.engine import FloatImage


def test_batch_continues_after_corrupt_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Runner:
        def __init__(self, *_: object) -> None:
            pass

        def infer(self, pixels: FloatImage) -> FloatImage:
            return pixels.repeat(2, 0).repeat(2, 1)

    monkeypatch.setattr(worker, "MnnRunner", Runner)
    bad, good, model = tmp_path / "bad.png", tmp_path / "good.png", tmp_path / "model.mnn"
    bad.write_bytes(b"not an image")
    Image.new("RGB", (19, 11), "red").save(good)
    model.touch()
    request = UpscaleRequest(
        images=(bad, good),
        model_path=model,
        output_dir=tmp_path / "output",
        profile=ModelProfile(scale=2),
        tile_size=16,
    )
    assert worker.run_batch(request) == 1
    events = [
        json.loads(line[len(worker.EVENT_PREFIX) :])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(worker.EVENT_PREFIX)
    ]
    assert any(e["event"] == "image_error" and e["index"] == 0 for e in events)
    assert events[-1] == {"event": "complete", "succeeded": 1, "failed": 1}
    with Image.open(request.output_dir / "good_2x.png") as result:
        assert result.size == (38, 22)
    assert not request.staging_path.exists()
