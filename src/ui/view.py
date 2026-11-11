"""Load the Qt Quick interface for a running application."""

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine

from src.logic.image_queue import PREVIEW_PROVIDER
from src.ui.controller import AppController
from src.ui.preview import PreviewProvider

if TYPE_CHECKING:
    from src.application import Entropy

QML = Path(__file__).parent / 'qml'


class Ui:
    """Own the QML view model and create engines that display it."""

    def __init__(self, app: Entropy) -> None:
        self.app = app
        self.controller = AppController(app)

    def load(self) -> QQmlApplicationEngine:
        """Load the packaged QML workspace with the typed view model."""
        engine = QQmlApplicationEngine()
        self.controller.setParent(engine)
        engine.addImportPath(str(QML))
        engine.addImageProvider(PREVIEW_PROVIDER, PreviewProvider())
        engine.setInitialProperties({'controller': self.controller})
        engine.load(QUrl.fromLocalFile(str(QML / 'Main.qml')))
        return engine

    def save_settings(self) -> None:
        """Persist preferences owned by the interface."""
        self.controller.save_settings()
