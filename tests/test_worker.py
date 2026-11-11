"""A failed image must not hide successful work or stop the remaining batch."""

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import src
from src import application
from src import worker as worker_package
from src.core.config import ModelProfile, UpscaleRequest
from src.core.events import Complete, ImageError, RuntimeReady, Saved, WorkerEvent, decode
from src.core.imaging import FloatImage
from src.worker import engine
from src.worker import process as worker


def events(output: str) -> list[WorkerEvent]:
    """Parse the protocol lines from captured worker stdout, skipping other output."""
    return [event for line in output.splitlines() if (event := decode(line)) is not None]


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("platform_name,backend_id", [("linux", 3), ("win32", 3), ("darwin", 1)])
def test_probe_reports_platform_gpu_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    available: bool,
    platform_name: str,
    backend_id: int,
) -> None:
    configurations: list[tuple[dict[str, int], ...]] = []

    def create_runtime(config: tuple[dict[str, int], ...]) -> tuple[object, tuple[bool]]:
        configurations.append(config)
        return object(), (available,)

    mnn = SimpleNamespace(
        __file__="test-runtime/MNN/__init__.py",
        Interpreter=SimpleNamespace(createRuntime=create_runtime),
    )
    monkeypatch.setattr(sys, "argv", ["worker", "--probe"])
    monkeypatch.setattr(engine, "sys", SimpleNamespace(platform=platform_name))
    monkeypatch.setattr(worker, "import_mnn", lambda: mnn)
    assert worker.main() == 0
    assert configurations == [({"backend": backend_id},)]
    assert events(capsys.readouterr().out) == [
        RuntimeReady(available=available, runtime_path=mnn.__file__)
    ]


def test_job_reads_its_request_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tmp_path / "input.png"
    Image.new("RGB", (6, 4)).save(image)
    request = UpscaleRequest(images=(image,), output_dir=tmp_path / "output", output_scale=0.5)
    stdin = SimpleNamespace(buffer=io.BytesIO(request.model_dump_json().encode()))
    monkeypatch.setattr(sys, "argv", ["worker", "--job"])
    monkeypatch.setattr(sys, "stdin", stdin)
    assert worker.main() == 0
    assert events(capsys.readouterr().out)[-1] == Complete(succeeded=1, failed=0)


def test_unknown_mode_reports_an_error_event(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["worker", "--nonsense"])
    assert worker.main() == 1
    (event,) = events(capsys.readouterr().out)
    assert event.event == "error"


def test_application_entry_point_dispatches_worker_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run_worker() -> int:
        calls.append(sys.argv[1:])
        return 7

    def run_gui() -> int:
        pytest.fail("Worker mode must not launch the GUI")

    monkeypatch.setattr(sys, "argv", ["Entropy.exe", "--worker", "--probe"])
    monkeypatch.setattr(worker_package, "main", run_worker)
    monkeypatch.setattr(application, "run", run_gui)
    assert src.main() == 7
    assert calls == [["--probe"]]


class DoublingRunner:
    def __init__(self, *_: object) -> None:
        pass

    def infer(self, pixels: FloatImage) -> FloatImage:
        return pixels.repeat(2, 0).repeat(2, 1)


def test_batch_continues_after_corrupt_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worker, "MnnRunner", DoublingRunner)
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
    reported = events(capsys.readouterr().out)
    assert any(isinstance(e, ImageError) and e.index == 0 for e in reported)
    assert reported[-1] == Complete(succeeded=1, failed=1)
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
    initialized: list[int] = []

    class Runner:
        def __init__(self, path: str, profile: ModelProfile) -> None:
            initialized.append(profile.scale)

        def infer(self, pixels: FloatImage) -> FloatImage:
            return pixels.repeat(4, 0).repeat(4, 1)

    def no_download() -> Path:
        pytest.fail("Resizing must not install an enhancement model")

    monkeypatch.setattr(worker, "MnnRunner", Runner)
    monkeypatch.setattr(worker, "prepare_model", no_download)
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
    saved = next(e for e in events(capsys.readouterr().out) if isinstance(e, Saved))
    assert saved.output_scale == scale
    assert saved.output == destination
    assert not request.staging_path.exists()
