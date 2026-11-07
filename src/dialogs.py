"""Configure Qt's native Linux dialogs to use xdg-desktop-portal."""

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo

logger = logging.getLogger(__name__)


def configure_file_portal() -> None:
    """Select the portal platform theme before constructing QGuiApplication.

    Qt owns the asynchronous D-Bus request and exports the correct transient
    parent on Wayland. QML FileDialog/FolderDialog retain their native defaults.
    On systems without the plugin, Qt can still use its built-in QML picker.
    """
    if sys.platform != "linux":
        return
    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    if not (plugins / "platformthemes" / "libqxdgdesktopportal.so").is_file():
        logger.warning(
            "Qt's xdg-desktop-portal plugin is missing; native portal dialogs unavailable"
        )
        return
    os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"
