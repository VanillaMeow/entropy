"""Qt Quick loading, view-model actions, and subprocess lifecycle checks."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QEventLoop, QObject, QPointF, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from src.app import create_engine  # noqa: E402
from src.controller import AppController  # noqa: E402
from src.process import WorkerProcess  # noqa: E402


@pytest.fixture(scope="module")
def qt_app() -> QGuiApplication:
    QQuickStyle.setStyle("Material")
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def controller(qt_app: QGuiApplication, tmp_path: Path) -> AppController:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return AppController(settings=settings, start_setup=False)


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
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not model_dir.exists()


def make_ready(controller: AppController, tmp_path: Path) -> Path:
    image = tmp_path / "input.png"
    Image.new("RGBA", (20, 12), (100, 150, 200, 80)).save(image)
    controller.add_paths([image, image, tmp_path])
    controller.outputDirectory = str(tmp_path / "output")
    controller._handle_event({"event": "model_ready"})
    controller._handle_event({"event": "runtime_ready", "available": True})
    return image


def test_queue_and_automatic_model(controller: AppController, tmp_path: Path) -> None:
    image = make_ready(controller, tmp_path)
    assert controller.queueCount == 1
    assert controller.originalUrl.toLocalFile() == str(image)
    assert controller.modelReady and controller.canStart
    assert not controller.hasResult
    controller._handle_event(
        {"event": "saved", "index": 0, "source": str(image), "output": str(image)}
    )
    assert controller.hasResult
    assert controller.resultUrl.toLocalFile() == str(image)
    controller.removeSelected()
    assert controller.queueCount == 0
    assert controller.selectedIndex == -1
    assert controller.originalUrl.isEmpty()


@pytest.mark.parametrize("dark,width", [(True, 1320), (False, 1320), (True, 800)])
def test_qml_workspace_loads_in_both_themes_and_compact_layout(
    qt_app: QGuiApplication, controller: AppController, tmp_path: Path, dark: bool, width: int
) -> None:
    make_ready(controller, tmp_path)
    controller.darkTheme = dark
    engine = create_engine(controller)
    assert engine.rootObjects()
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    warnings = []
    engine.warnings.connect(
        lambda messages: warnings.extend(message.toString() for message in messages)
    )
    window.setWidth(width)
    qt_app.processEvents()
    button = window.findChild(QObject, "upscaleButton")
    assert button and button.property("enabled")
    assert window.findChild(QObject, "imageQueue")
    result = tmp_path / "result.png"
    Image.new("RGBA", (80, 48), (100, 150, 200, 80)).save(result)
    controller._handle_event({"event": "saved", "index": 0, "output": str(result)})
    QTest.qWait(100)
    assert controller.hasResult
    frame = window.findChild(QQuickItem, "comparisonFrame")
    before = frame.mapToScene(QPointF(frame.width() * 0.25, frame.height() * 0.5))
    after = frame.mapToScene(QPointF(frame.width() * 0.75, frame.height() * 0.5))
    screenshot = window.grabWindow()
    left = screenshot.pixelColor(round(before.x()), round(before.y()))
    right = screenshot.pixelColor(round(after.x()), round(after.y()))
    assert max(abs(a - b) for a, b in zip(left.getRgb(), right.getRgb(), strict=True)) <= 1
    if width < 1060:
        window.setProperty("settingsOpen", True)
        qt_app.processEvents()
    window.setProperty("diagnosticsOpen", True)
    qt_app.processEvents()
    retry = window.findChild(QObject, "retrySetupButton")
    assert retry and retry.property("enabled")
    controller.removeSelected()
    qt_app.processEvents()
    assert controller.selectedIndex == -1
    assert not warnings, warnings
    window.close()
    engine.deleteLater()
    qt_app.processEvents()


def test_batch_uses_default_model_and_locks_settings(
    controller: AppController, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_ready(controller, tmp_path)
    starts = []
    monkeypatch.setattr(controller._worker, "start", starts.append)
    controller.startBatch()
    assert controller._request.model_path is None
    assert controller._request.profile.scale == 4
    assert controller._request.output_scale == 4
    assert starts
    controller._finished(0, True)
    controller.shutdown()


def test_scale_controls_accept_presets_and_custom_percent(
    qt_app: QGuiApplication, controller: AppController, tmp_path: Path
) -> None:
    make_ready(controller, tmp_path)
    engine = create_engine(controller)
    window = engine.rootObjects()[0]
    warnings = []
    engine.warnings.connect(
        lambda messages: warnings.extend(message.toString() for message in messages)
    )
    presets = window.findChild(QQuickItem, "scalePresets")
    percent = window.findChild(QQuickItem, "scalePercent")
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
    assert window.findChild(QObject, "upscaleButton").property("text") == "Downscale image"
    controller._handle_event(
        {
            "event": "saved",
            "index": 0,
            "output": str(tmp_path / "result.png"),
            "output_scale": 0.5,
        }
    )
    controller.outputScale = 4
    assert window.findChild(QObject, "resultScaleLabel").property("text") == "Result · 0.5×"
    assert not warnings, warnings
    window.close()
    engine.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("scale", [0.5, 1.25, 2, 3])
def test_scale_is_snapshotted_and_preserved_with_result(
    controller: AppController, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scale: float
) -> None:
    make_ready(controller, tmp_path)
    controller.outputScale = scale
    monkeypatch.setattr(controller._worker, "start", lambda _: None)
    controller.startBatch()
    assert controller._request.output_scale == scale
    assert controller._request.profile.scale == 4
    controller._handle_event(
        {
            "event": "saved",
            "index": 0,
            "output": str(tmp_path / "result.png"),
            "output_scale": scale,
        }
    )
    controller._finished(0, False)
    controller.outputScale = 4
    assert controller.resultScale == scale
    controller.outputScale = scale
    controller.shutdown()
    restored = AppController(settings=controller._settings, start_setup=False)
    assert restored.outputScale == scale


def test_downscale_needs_no_model_or_gpu(controller: AppController, tmp_path: Path) -> None:
    image = tmp_path / "input.png"
    Image.new("RGB", (10, 10)).save(image)
    controller.add_paths([image])
    assert not controller.canStart
    controller.outputScale = 0.5
    assert controller.canStart
    controller.outputScale = 1
    assert controller.canStart
    controller.outputScale = 1.01
    assert not controller.canStart


def test_saved_backend_is_ignored_and_runtime_failure_blocks_upscaling(
    controller: AppController, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller._settings.setValue("backend", "Vulkan")
    restored = AppController(settings=controller._settings, start_setup=False)
    make_ready(restored, tmp_path)
    assert restored.canStart
    assert restored.metaObject().indexOfProperty("backend") == -1
    assert restored.metaObject().indexOfProperty("backendStatus") == -1
    restored._handle_event({"event": "runtime_ready", "available": False})
    assert not restored.canStart
    assert restored.hasError
    assert "GPU runtime: unavailable" in restored.diagnostics
    starts = []
    monkeypatch.setattr(restored._worker, "start", starts.append)
    restored.prepare()
    assert starts == ["--prepare"]
    restored._handle_event({"event": "runtime_ready", "available": True})
    restored._finished(0, False)
    assert restored.canStart and not restored.hasError
    restored.startBatch()
    assert "backend" not in restored._request.model_dump()
    restored._finished(0, False)
    restored.shutdown()


def test_scale_validation_and_busy_lock(controller: AppController) -> None:
    controller.outputScale = 1.5
    for invalid in [0, -1, 0.09, 4.01, float("nan"), float("inf")]:
        controller.outputScale = invalid
        assert controller.outputScale == 1.5
    controller._worker._process = QObject()
    try:
        controller.outputScale = 2
        assert controller.outputScale == 1.5
    finally:
        controller._worker._process = None


@pytest.mark.parametrize("stored", ["broken", "nan", "inf", "0", "5"])
def test_invalid_saved_scale_uses_default(controller: AppController, stored: str) -> None:
    controller._settings.setValue("outputScale", stored)
    restored = AppController(settings=controller._settings, start_setup=False)
    assert restored.outputScale == 4


def test_urls_from_portal_and_drops(controller: AppController, tmp_path: Path) -> None:
    from PySide6.QtCore import QUrl

    image = tmp_path / "with spaces.png"
    Image.new("RGB", (4, 5)).save(image)
    controller.addUrls([QUrl.fromLocalFile(str(image)), "https://example.com/image.png"])
    assert controller.queueCount == 1
    controller.setOutputFolder(QUrl.fromLocalFile(str(tmp_path)))
    assert controller.outputDirectory == str(tmp_path)


def test_subprocess_cancellation_reaps_child(qt_app: QGuiApplication) -> None:
    process = WorkerProcess()
    finished = []
    loop = QEventLoop()
    process.finished.connect(
        lambda code, cancelled: (finished.append((code, cancelled)), loop.quit())
    )
    process.start("--probe")
    process.cancel()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5000)
    loop.exec()
    timer.stop()
    process.shutdown()
    assert finished and finished[0][1] is True
    assert not process.running


def test_compiled_worker_launches_the_application_executable(
    qt_app: QGuiApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QProcess

    from src import process as process_module

    launches = []
    monkeypatch.setattr(process_module, "is_compiled", lambda: True)
    monkeypatch.setattr(
        QProcess,
        "start",
        lambda self, executable, arguments: launches.append((executable, arguments)),
    )
    process = WorkerProcess()
    process.start("--prepare")
    assert launches == [(sys.executable, ["--worker", "--prepare"])]
    process.shutdown()
