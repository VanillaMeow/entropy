"""Load the Qt Quick interface for a running application."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine

from entropy.logic.image_queue import PREVIEW_PROVIDER
from entropy.ui.controller import AppController
from entropy.ui.preview import PreviewProvider

if TYPE_CHECKING:
    from entropy.application import Entropy

QML = Path(__file__).parent / 'qml'


class Ui:
    """Own the QML view model and create engines that display it."""

    def __init__(self, app: Entropy) -> None:
        self.app = app
        self.controller = AppController(app)

    def load(self) -> QQmlApplicationEngine:
        """Load the packaged QML workspace with the typed view model."""
        engine = QQmlApplicationEngine()

        # The engine owns the controller so QML never outlives its view model
        self.controller.setParent(engine)

        engine.addImportPath(str(QML))
        engine.addImageProvider(PREVIEW_PROVIDER, PreviewProvider())
        engine.setInitialProperties({'controller': self.controller})
        engine.load(QUrl.fromLocalFile(str(QML / 'Main.qml')))

        return engine

    def save_settings(self) -> None:
        """Persist preferences owned by the interface."""
        self.controller.save_settings()
