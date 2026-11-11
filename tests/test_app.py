"""Qt Quick loading, view-model actions, and subprocess lifecycle checks."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import (  # noqa: E402
    QCoreApplication,
    QEventLoop,
    QObject,
    QPointF,
    QProcess,
    QSettings,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlError  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from src.application import Entropy  # noqa: E402
from src.core.config import UpscaleRequest  # noqa: E402
from src.core.events import Error, ModelReady, RuntimeReady, Saved, WorkerEvent  # noqa: E402
from src.logic import worker_host  # noqa: E402
from src.logic.worker_host import WorkerHost, WorkerMode  # noqa: E402
from src.ui.controller import AppController  # noqa: E402


@pytest.fixture(scope="module")
def qt_app() -> QGuiApplication:
    QQuickStyle.setStyle("Material")
    existing = QGuiApplication.instance()
    return existing if isinstance(existing, QGuiApplication) else QGuiApplication([])


@pytest.fixture
def app(qt_app: QGuiApplication, tmp_path: Path) -> Entropy:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return Entropy(settings=settings, start_setup=False)


@pytest.fixture
def controller(app: Entropy) -> AppController:
    return app.ui.controller


class Starts:
    """Record worker starts instead of launching a process."""

    def __init__(self) -> None:
        self.calls: list[tuple[WorkerMode, UpscaleRequest | None]] = []

    def __call__(self, mode: WorkerMode, request: UpscaleRequest | None = None) -> None:
        self.calls.append((mode, request))


def saved(index: int, output: Path, scale: float = 4.0) -> Saved:
    return Saved(index=index, source=output, output=output, output_scale=scale)


def window_of(engine: QQmlApplicationEngine) -> QQuickWindow:
    roots = engine.rootObjects()
    assert roots
    window = roots[0]
    assert isinstance(window, QQuickWindow)
    return window


def child(window: QQuickWindow, name: str) -> QObject:
    found = window.findChild(QObject, name)
    assert found is not None, name
    return found


def item(window: QQuickWindow, name: str) -> QQuickItem:
    found = window.findChild(QQuickItem, name)
    assert found is not None, name
    return found


def rgba(color: QColor) -> tuple[int, int, int, int]:
    return color.red(), color.green(), color.blue(), color.alpha()


def collect_warnings(engine: QQmlApplicationEngine) -> list[str]:
    warnings: list[str] = []

    def record(messages: list[QQmlError]) -> None:
        warnings.extend(message.toString() for message in messages)

    engine.warnings.connect(record)
    return warnings


def run_until_finished(host: WorkerHost, finished: list[tuple[int, bool]]) -> None:
    loop = QEventLoop()

    def done(code: int, cancelled: bool) -> None:
        finished.append((code, cancelled))
        loop.quit()

    host.finished.connect(done)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5000)
    loop.exec()
    timer.stop()


def test_startup_check_loads_workspace_without_model_setup(tmp_path: Path) -> None:
    model_dir = tmp_path / "models"
    environment = os.environ.copy()
    environment.update(
        ENTROPY_STARTUP_CHECK="1",
        ENTROPY_MODEL_DIR=str(model_dir),
        XDG_CONFIG_HOME=str(tmp_path / "settings"),
        QT_QPA_PLATFORM="offscreen",
        QT_QUICK_BACKEND="software",
    )
    result = subprocess.run(
        [sys.executable, "-m", "src"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not model_dir.exists()


def make_ready(app: Entropy, tmp_path: Path) -> Path:
    image = tmp_path / "input.png"
    Image.new("RGBA", (20, 12), (100, 150, 200, 80)).save(image)
    app.session.add_paths([image, image, tmp_path])
    app.ui.controller.outputDirectory = str(tmp_path / "output")
    app.session.handle_event(ModelReady())
    app.session.handle_event(RuntimeReady(available=True))
    return image


def test_queue_and_automatic_model(app: Entropy, controller: AppController, tmp_path: Path) -> None:
    image = make_ready(app, tmp_path)
    assert controller.queueCount == 1
    assert controller.originalUrl.toLocalFile() == str(image)
    assert controller.modelReady and controller.canStart
    assert not controller.hasResult
    app.session.handle_event(saved(0, image))
    assert controller.hasResult
    assert controller.resultUrl.toLocalFile() == str(image)
    controller.removeSelected()
    assert controller.queueCount == 0
    assert controller.selectedIndex == -1
    assert controller.originalUrl.isEmpty()


@pytest.mark.parametrize("dark,width", [(True, 1320), (False, 1320), (True, 800)])
def test_qml_workspace_loads_in_both_themes_and_compact_layout(
    qt_app: QGuiApplication,
    app: Entropy,
    controller: AppController,
    tmp_path: Path,
    dark: bool,
    width: int,
) -> None:
    make_ready(app, tmp_path)
    controller.darkTheme = dark
    engine = app.ui.load()
    window = window_of(engine)
    warnings = collect_warnings(engine)
    window.setWidth(width)
    qt_app.processEvents()
    assert child(window, "upscaleButton").property("enabled")
    child(window, "imageQueue")
    result = tmp_path / "result.png"
    Image.new("RGBA", (80, 48), (100, 150, 200, 80)).save(result)
    app.session.handle_event(saved(0, result))
    QTest.qWait(100)
    assert controller.hasResult
    frame = item(window, "comparisonFrame")
    before = frame.mapToScene(QPointF(frame.width() * 0.25, frame.height() * 0.5))
    after = frame.mapToScene(QPointF(frame.width() * 0.75, frame.height() * 0.5))
    screenshot = window.grabWindow()
    left = screenshot.pixelColor(round(before.x()), round(before.y()))
    right = screenshot.pixelColor(round(after.x()), round(after.y()))
    assert max(abs(a - b) for a, b in zip(rgba(left), rgba(right), strict=True)) <= 1
    if width < 1060:
        window.setProperty("settingsOpen", True)
        qt_app.processEvents()
    window.setProperty("diagnosticsOpen", True)
    qt_app.processEvents()
    assert child(window, "retrySetupButton").property("enabled")
    controller.removeSelected()
    qt_app.processEvents()
    assert controller.selectedIndex == -1
    assert not warnings, warnings
    window.close()
    engine.deleteLater()
    qt_app.processEvents()


def test_batch_uses_default_model_and_locks_settings(
    app: Entropy, controller: AppController, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_ready(app, tmp_path)
    starts = Starts()
    monkeypatch.setattr(app.worker, "start", starts)
    controller.startBatch()
    request = app.session.request
    assert request is not None
    assert request.model_path is None
    assert request.profile.scale == 4
    assert request.output_scale == 4
    assert starts.calls == [("job", request)]
    app.session.handle_finished(0, True)
    controller.shutdown()


def test_scale_controls_accept_presets_and_custom_percent(
    qt_app: QGuiApplication, app: Entropy, controller: AppController, tmp_path: Path
) -> None:
    make_ready(app, tmp_path)
    engine = app.ui.load()
    window = window_of(engine)
    warnings = collect_warnings(engine)
    presets = item(window, "scalePresets")
    percent = item(window, "scalePercent")
    assert presets.property("currentIndex") == 7
    presets.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Up)
    assert controller.outputScale == 3
    assert percent.property("value") == 300
    percent.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for key in [Qt.Key.Key_1, Qt.Key.Key_3, Qt.Key.Key_7]:
        QTest.keyClick(window, key)
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert controller.outputScale == 1.37
    assert presets.property("currentIndex") == -1
    controller.outputScale = 0.5
    assert percent.property("value") == 50
    assert presets.property("currentIndex") == 1
    assert child(window, "upscaleButton").property("text") == "Downscale image"
    app.session.handle_event(saved(0, tmp_path / "result.png", 0.5))
    controller.outputScale = 4
    assert child(window, "resultScaleLabel").property("text") == "Result · 0.5×"
    assert not warnings, warnings
    window.close()
    engine.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("scale", [0.5, 1.25, 2, 3])
def test_scale_is_snapshotted_and_preserved_with_result(
    app: Entropy,
    controller: AppController,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scale: float,
) -> None:
    make_ready(app, tmp_path)
    controller.outputScale = scale
    monkeypatch.setattr(app.worker, "start", Starts())
    controller.startBatch()
    request = app.session.request
    assert request is not None
    assert request.output_scale == scale
    assert request.profile.scale == 4
    app.session.handle_event(saved(0, tmp_path / "result.png", scale))
    app.session.handle_finished(0, False)
    controller.outputScale = 4
    assert controller.resultScale == scale
    controller.outputScale = scale
    controller.shutdown()
    restored = Entropy(settings=app.settings.store, start_setup=False)
    assert restored.ui.controller.outputScale == scale


def test_downscale_needs_no_model_or_gpu(
    app: Entropy, controller: AppController, tmp_path: Path
) -> None:
    image = tmp_path / "input.png"
    Image.new("RGB", (10, 10)).save(image)
    app.session.add_paths([image])
    assert not controller.canStart
    controller.outputScale = 0.5
    assert controller.canStart
    controller.outputScale = 1
    assert controller.canStart
    controller.outputScale = 1.01
    assert not controller.canStart


def test_saved_backend_is_ignored_and_runtime_failure_blocks_upscaling(
    app: Entropy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.settings.set("backend", "Vulkan")
    restored = Entropy(settings=app.settings.store, start_setup=False)
    controller = restored.ui.controller
    make_ready(restored, tmp_path)
    assert controller.canStart
    assert controller.metaObject().indexOfProperty("backend") == -1
    assert controller.metaObject().indexOfProperty("backendStatus") == -1
    restored.session.handle_event(RuntimeReady(available=False))
    assert not controller.canStart
    assert controller.hasError
    assert "GPU runtime: unavailable" in controller.diagnostics
    starts = Starts()
    monkeypatch.setattr(restored.worker, "start", starts)
    controller.prepare()
    assert starts.calls == [("prepare", None)]
    restored.session.handle_event(RuntimeReady(available=True))
    restored.session.handle_finished(0, False)
    assert controller.canStart and not controller.hasError
    controller.startBatch()
    request = restored.session.request
    assert request is not None
    assert "backend" not in request.model_dump()
    restored.session.handle_finished(0, False)
    controller.shutdown()


def test_scale_validation_and_busy_lock(
    controller: AppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller.outputScale = 1.5
    for invalid in [0, -1, 0.09, 4.01, float("nan"), float("inf")]:
        controller.outputScale = invalid
        assert controller.outputScale == 1.5

    def always_running(_: WorkerHost) -> bool:
        return True

    monkeypatch.setattr(WorkerHost, "running", property(always_running))
    controller.outputScale = 2
    assert controller.outputScale == 1.5


@pytest.mark.parametrize("stored", ["broken", "nan", "inf", "0", "5"])
def test_invalid_saved_scale_uses_default(app: Entropy, stored: str) -> None:
    app.settings.set("outputScale", stored)
    restored = Entropy(settings=app.settings.store, start_setup=False)
    assert restored.ui.controller.outputScale == 4


@pytest.mark.parametrize(("key", "stored"), [("tileSize", "huge"), ("padding", "-3")])
def test_invalid_saved_tiling_uses_default(app: Entropy, key: str, stored: str) -> None:
    app.settings.set(key, stored)
    controller = Entropy(settings=app.settings.store, start_setup=False).ui.controller
    assert (controller.tileSize, controller.padding) == (128, 16)


def test_urls_from_portal_and_drops(controller: AppController, tmp_path: Path) -> None:
    image = tmp_path / "with spaces.png"
    Image.new("RGB", (4, 5)).save(image)
    controller.addUrls([QUrl.fromLocalFile(str(image)), "https://example.com/image.png"])
    assert controller.queueCount == 1
    controller.setOutputFolder(QUrl.fromLocalFile(str(tmp_path)))
    assert controller.outputDirectory == str(tmp_path)


def test_subprocess_cancellation_reaps_child(qt_app: QGuiApplication) -> None:
    host = WorkerHost()
    finished: list[tuple[int, bool]] = []
    host.start("probe")
    host.cancel()
    run_until_finished(host, finished)
    host.shutdown()
    assert finished and finished[0][1] is True
    assert not host.running


def test_compiled_worker_launches_the_application_executable(
    qt_app: QGuiApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    launches: list[tuple[str, list[str]]] = []

    def application_file_path() -> str:
        return "C:/Program Files/Entropy/app/Entropy.exe"

    def start(_: QProcess, executable: str, arguments: list[str]) -> None:
        launches.append((executable, arguments))

    monkeypatch.setattr(worker_host, "is_compiled", lambda: True)
    monkeypatch.setattr(sys, "executable", "/missing/python.exe")
    monkeypatch.setattr(QCoreApplication, "applicationFilePath", application_file_path)
    monkeypatch.setattr(QProcess, "start", start)
    host = WorkerHost()
    host.start("prepare")
    assert launches == [("C:/Program Files/Entropy/app/Entropy.exe", ["--worker", "--prepare"])]
    host.shutdown()


def test_job_requires_a_request(qt_app: QGuiApplication, tmp_path: Path) -> None:
    host = WorkerHost()
    with pytest.raises(ValueError, match="request is required"):
        host.start("job")
    request = UpscaleRequest(images=(tmp_path / "a.png",), output_dir=tmp_path)
    with pytest.raises(ValueError, match="request is required"):
        host.start("probe", request)
    assert not host.running


def test_failed_worker_start_keeps_the_original_error(
    qt_app: QGuiApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "executable", "/missing/entropy/python.exe")
    host = WorkerHost()
    events: list[WorkerEvent] = []
    finished: list[tuple[int, bool]] = []
    host.received.connect(events.append)
    host.start("probe")
    run_until_finished(host, finished)
    host.shutdown()
    assert finished == [(-1, False)]
    (event,) = events
    assert isinstance(event, Error)
    assert "crashed" not in event.message
    assert not host.running
