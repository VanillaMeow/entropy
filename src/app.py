"""Qt Quick application bootstrap."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from .controller import AppController
from .dialogs import configure_file_portal
from .paths import is_compiled
from .preview import PreviewProvider
from .version import application_version


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
    app.setApplicationVersion(application_version())
    if is_compiled():
        app.setWindowIcon(QIcon(str(Path(sys.executable).with_name("Entropy.ico"))))
    font = app.font()
    font.setPointSizeF(max(12, font.pointSizeF()))
    app.setFont(font)
    startup_check = os.environ.get("ENTROPY_STARTUP_CHECK") == "1"
    controller = AppController(start_setup=not startup_check)
    engine = create_engine(controller)
    if not engine.rootObjects():
        controller.shutdown()
        return 1
    if startup_check:
        for window in engine.rootObjects():
            window.close()
        return 0
    app.aboutToQuit.connect(controller.shutdown)
    return app.exec()
