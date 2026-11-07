"""Qt Quick application bootstrap."""

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from placeholder_upscaler.controller import AppController
from placeholder_upscaler.dialogs import configure_file_portal
from placeholder_upscaler.preview import PreviewProvider


def create_engine(controller: AppController) -> QQmlApplicationEngine:
    """Load the packaged QML workspace with an explicit, typed view model."""
    qml = Path(__file__).parent / "qml"
    engine = QQmlApplicationEngine()
    controller.setParent(engine)
    engine.addImportPath(str(qml))
    engine.addImageProvider("preview", PreviewProvider())
    engine.setInitialProperties({"controller": controller})
    engine.load(QUrl.fromLocalFile(str(qml / "Main.qml")))
    return engine


def run() -> int:
    """Launch Material Qt Quick with native portal file dialogs on Linux."""
    configure_file_portal()
    QQuickStyle.setStyle("Material")
    app = QGuiApplication(sys.argv)
    app.setOrganizationName("Entropy")
    app.setApplicationName("Entropy")
    app.setApplicationDisplayName("Entropy")
    font = app.font()
    font.setPointSizeF(max(12, font.pointSizeF()))
    app.setFont(font)
    controller = AppController()
    engine = create_engine(controller)
    if not engine.rootObjects():
        controller.shutdown()
        return 1
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()
