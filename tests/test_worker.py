"""A failed image must not hide successful work or stop the remaining batch."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src import worker
from src.config import ModelProfile, UpscaleRequest
from src.engine import FloatImage


@pytest.mark.parametrize("available", [False, True])
def test_probe_reports_opencl_readiness(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], available: bool
) -> None:
    configurations = []

    def create_runtime(config: tuple[dict[str, int], ...]) -> tuple[object, tuple[bool]]:
        configurations.append(config)
        return object(), (available,)

    mnn = SimpleNamespace(
        __file__="test-runtime/MNN/__init__.py",
        Interpreter=SimpleNamespace(createRuntime=create_runtime),
    )
    monkeypatch.setattr(sys, "argv", ["worker", "--probe"])
    monkeypatch.setattr(worker, "import_mnn", lambda: mnn)
    assert worker.main() == 0
    assert configurations == [({"backend": 3},)]
    event = json.loads(capsys.readouterr().out.strip().removeprefix(worker.EVENT_PREFIX))
    assert event == {
        "event": "runtime_ready",
        "available": available,
        "runtime_path": mnn.__file__,
    }


def test_application_entry_point_dispatches_worker_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import src
    from src import app

    calls = []

    def run_worker() -> int:
        calls.append(sys.argv[1:])
        return 7

    monkeypatch.setattr(sys, "argv", ["Entropy.exe", "--worker", "--probe"])
    monkeypatch.setattr(worker, "main", run_worker)
    monkeypatch.setattr(app, "run", lambda: pytest.fail("Worker mode must not launch the GUI"))
    assert src.main() == 7
    assert calls == [["--probe"]]


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
        output_scale=2,
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


@pytest.mark.parametrize("scale", [0.1, 0.5, 1, 1.25, 1.5, 2, 3, 4])
def test_batch_exports_requested_scale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scale: float,
) -> None:
    initialized = []

    class Runner:
        def __init__(self, path: str, profile: ModelProfile) -> None:
            initialized.append(profile.scale)

        def infer(self, pixels: FloatImage) -> FloatImage:
            return pixels.repeat(4, 0).repeat(4, 1)

    def no_download() -> Path:
        pytest.fail("Resizing must not install an enhancement model")

    monkeypatch.setattr(worker, "MnnRunner", Runner)
    monkeypatch.setattr(worker, "_prepare_model", no_download)
    image, model = tmp_path / "input.png", tmp_path / "model.mnn"
    Image.new("RGBA", (19, 11), (100, 150, 200, 80)).save(image)
    if scale > 1:
        model.touch()
    request = UpscaleRequest(
        images=(image,),
        model_path=model,
        output_dir=tmp_path / "output",
        output_scale=scale,
        tile_size=16,
    )
    assert worker.run_batch(request) == 0
    assert initialized == ([4] if scale > 1 else [])
    destination = request.output_dir / f"input_{scale:g}x.png"
    with Image.open(destination) as result:
        assert result.size == (max(1, round(19 * scale)), max(1, round(11 * scale)))
        assert result.mode == "RGBA"
    events = [
        json.loads(line[len(worker.EVENT_PREFIX) :])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(worker.EVENT_PREFIX)
    ]
    saved = next(event for event in events if event["event"] == "saved")
    assert saved["output_scale"] == scale
    assert saved["output"] == str(destination)
    assert not request.staging_path.exists()
