"""Portal selection is configured before the GUI starts, with a logged fallback."""

import logging
from pathlib import Path

import pytest

from placeholder_upscaler import dialogs


def test_linux_selects_portal_theme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = tmp_path / "platformthemes" / "libqxdgdesktopportal.so"
    plugin.parent.mkdir()
    plugin.touch()
    monkeypatch.setattr(dialogs.sys, "platform", "linux")
    monkeypatch.setattr(dialogs.QLibraryInfo, "path", lambda _: str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORMTHEME", "kde")
    dialogs.configure_file_portal()
    assert dialogs.os.environ["QT_QPA_PLATFORMTHEME"] == "xdgdesktopportal"


def test_missing_portal_plugin_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(dialogs.sys, "platform", "linux")
    monkeypatch.setattr(dialogs.QLibraryInfo, "path", lambda _: str(tmp_path))
    monkeypatch.delenv("QT_QPA_PLATFORMTHEME", raising=False)
    with caplog.at_level(logging.WARNING):
        dialogs.configure_file_portal()
    assert "plugin is missing" in caplog.text
    assert "QT_QPA_PLATFORMTHEME" not in dialogs.os.environ
