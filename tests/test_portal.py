"""Opt-in verification of real native portal calls; no picker interaction required."""

import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(
    os.environ.get('ENTROPY_TEST_PORTAL') != '1',
    reason='Set ENTROPY_TEST_PORTAL=1 in a desktop session',
)
def test_native_file_and_folder_portal_requests() -> None:
    # Runs in a fresh interpreter, opening each picker in turn while
    # dbus-monitor records the requests that reach the desktop portal
    script = r"""
import subprocess
from tempfile import TemporaryDirectory
from pathlib import Path
from PySide6.QtCore import QSettings, QTimer, QObject, QMetaObject, Qt, Q_ARG
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuickControls2 import QQuickStyle
from entropy.ui.dialogs import configure_file_portal
from entropy.application import Entropy

configure_file_portal()
QQuickStyle.setStyle("Material")
monitor = subprocess.Popen([
    "dbus-monitor", "--session",
    "type='method_call',interface='org.freedesktop.portal.FileChooser',member='OpenFile'"
], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    with TemporaryDirectory(prefix="entropy-portal-test-") as directory:
        app = QGuiApplication([])
        settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
        entropy = Entropy(settings=settings, start_setup=False)
        entropy.ui.controller.outputDirectory = directory
        engine = entropy.ui.load()
        assert engine.rootObjects()
        window = engine.rootObjects()[0]
        pickers = window.findChild(QObject, "filePickers")
        def choose(purpose):
            assert QMetaObject.invokeMethod(
                pickers, "choose", Qt.ConnectionType.DirectConnection, Q_ARG(str, purpose))
        for i, purpose in enumerate(["images", "inputFolder", "outputFolder"]):
            QTimer.singleShot(300 + i * 900, lambda purpose=purpose: choose(purpose))
            QTimer.singleShot(850 + i * 900, lambda: pickers.setProperty("purpose", ""))
        QTimer.singleShot(3100, window.close)
        app.exec()
finally:
    monitor.terminate()
    out, err = monitor.communicate(timeout=5)
assert out.count("member=OpenFile") == 3, out
assert 'string "Choose images to upscale"' in out, out
assert 'string "Add images from a folder"' in out, out
assert 'string "Choose output folder"' in out, out
assert out.count('string "directory"') == 3, out
assert out.count('variant             boolean true') >= 3, out
print("Verified exactly three native portal requests: images, input folder, output folder.")
"""

    environment = os.environ.copy()
    environment.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
    result = subprocess.run(
        [sys.executable, '-c', script],
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert 'TypeError' not in result.stderr, result.stderr
