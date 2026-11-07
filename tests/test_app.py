"""Qt Quick loading, view-model actions, and subprocess lifecycle checks."""

import os
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QEventLoop, QObject, QPointF, QSettings, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from placeholder_upscaler.app import create_engine  # noqa: E402
from placeholder_upscaler.controller import AppController  # noqa: E402
from placeholder_upscaler.process import WorkerProcess  # noqa: E402


@pytest.fixture(scope="module")
def qt_app() -> QGuiApplication:
    QQuickStyle.setStyle("Material")
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def controller(qt_app: QGuiApplication, tmp_path: Path) -> AppController:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return AppController(settings=settings, start_setup=False)


def make_ready(controller: AppController, tmp_path: Path) -> Path:
    image = tmp_path / "input.png"
    Image.new("RGBA", (20, 12), (100, 150, 200, 80)).save(image)
    controller.add_paths([image, image, tmp_path])
    controller.outputDirectory = str(tmp_path / "output")
    controller._handle_event({"event": "model_ready"})
    controller._handle_event({"event": "backends", "available": {"OpenCL": True, "Vulkan": True}})
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
    assert starts
    controller._finished(0, True)
    controller.shutdown()


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
