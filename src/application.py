"""The desktop application: owns the session and the interface and wires them together."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QGuiApplication, QIcon, QWindow
from PySide6.QtQuickControls2 import QQuickStyle

from src.logic.session import Session
from src.logic.settings import Settings
from src.logic.worker_host import WorkerHost
from src.paths import is_compiled
from src.ui.dialogs import configure_file_portal
from src.ui.view import Ui
from src.version import application_version

MIN_FONT_SIZE = 12


class Entropy:
    """Hold every long-lived part of the desktop process.

    Parts receive this object so they can reach each other. The session never
    touches ``ui``: it reports changes through signals the interface connects to.
    Constructors may only use parts built before them.
    """

    def __init__(self, *, settings: QSettings | None = None, start_setup: bool = True) -> None:
        self.settings = Settings(settings)
        self.worker = WorkerHost()
        self.session = Session(self)
        self.ui = Ui(self)
        if start_setup:
            QTimer.singleShot(0, self.session.prepare)

    def shutdown(self) -> None:
        """Reap the worker and persist preferences; safe to call more than once."""
        self.worker.shutdown()
        self.session.save_settings()
        self.ui.save_settings()


def run() -> int:
    """Launch Material Qt Quick with native portal file dialogs on Linux."""
    configure_file_portal()
    QQuickStyle.setStyle('Material')
    qt = QGuiApplication(sys.argv)
    qt.setOrganizationName('Entropy')
    qt.setApplicationName('Entropy')
    qt.setApplicationDisplayName('Entropy')
    qt.setApplicationVersion(application_version())
    if is_compiled():
        qt.setWindowIcon(QIcon(str(Path(sys.executable).with_name('Entropy.ico'))))
    font = qt.font()
    font.setPointSizeF(max(MIN_FONT_SIZE, font.pointSizeF()))
    qt.setFont(font)

    # Packaging checks that QML loads without starting model setup or the worker
    startup_check = os.environ.get('ENTROPY_STARTUP_CHECK') == '1'
    app = Entropy(start_setup=not startup_check)
    engine = app.ui.load()
    if not engine.rootObjects():
        app.shutdown()
        return 1
    if startup_check:
        for window in engine.rootObjects():
            if isinstance(window, QWindow):
                window.close()
        return 0
    qt.aboutToQuit.connect(app.shutdown)
    return qt.exec()
