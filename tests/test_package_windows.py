"""Validate the standalone application and Qt Installer Framework packaging contract."""

import shutil
import subprocess
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from PIL import Image

from scripts import package_windows

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def build_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    project = tmp_path / "project with spaces"
    project.mkdir()
    for filename in ("README.md", "LICENSE"):
        shutil.copy2(PROJECT / filename, project / filename)
    for directory in ("src", "packaging", "flatpak"):
        shutil.copytree(
            PROJECT / directory,
            project / directory,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    binarycreator = tmp_path / "Qt IFW" / "binarycreator.exe"
    binarycreator.parent.mkdir()
    binarycreator.touch()
    native_root = tmp_path / "native"
    native = native_root / "gpu-runtime"
    (native / "MNN").mkdir(parents=True)
    (native / "MNN" / "__init__.py").write_text("from _mnncengine import *\n")
    (native / "_mnncengine.pyd").write_bytes(b"GPU runtime")
    monkeypatch.setattr(
        package_windows,
        "sys",
        SimpleNamespace(platform="win32", maxsize=2**63 - 1, base_prefix=str(tmp_path / "python")),
    )
    monkeypatch.setattr(package_windows.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(package_windows, "runtime_root", lambda: native_root)
    monkeypatch.setattr(
        package_windows,
        "activate_local_runtime",
        lambda: {"directory": native.name, "compiled_backends": ["OpenCL", "Vulkan"]},
    )
    monkeypatch.setattr(package_windows, "application_version", lambda: "0.1.0-alpha.1")
    monkeypatch.setattr(package_windows, "distributions", lambda: ())

    def fake_model(*, directory: Path) -> Path:
        directory.mkdir()
        model = directory / "model.mnn"
        model.write_bytes(b"verified model")
        (directory / "model.license.txt").write_bytes(b"model license")
        return model

    monkeypatch.setattr(package_windows, "ensure_default_model", fake_model)
    return project, binarycreator


def fake_deploy(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    assert command[0] == "pyside6-deploy"
    assert "--no-install" in command
    assert kwargs["check"] is True
    staging = Path(kwargs["cwd"])
    config = ConfigParser()
    config.read(command[command.index("--config-file") + 1])
    assert config["nuitka"]["mode"] == "standalone"
    assert "src/qml/Main.qml" in config["qt"]["qml_files"]
    assert "--include-package=MNN" in config["nuitka"]["extra_args"]
    assert "--include-distribution-metadata=entropy" in config["nuitka"]["extra_args"]
    assert "--windows-console-mode=attach" in config["nuitka"]["extra_args"]
    assert "--file-version=0.1.0" in config["nuitka"]["extra_args"]
    native = Path(kwargs["env"]["PYTHONPATH"].split(package_windows.os.pathsep)[0])
    assert (native / "_mnncengine.pyd").is_file()
    payload = staging / "frozen" / "Entropy.dist"
    payload.mkdir(parents=True)
    (payload / "Entropy.exe").write_bytes(b"standalone application")
    shutil.copy2(native / "_mnncengine.pyd", payload / "_mnncengine.pyd")
    shutil.copytree(staging / "src" / "qml", payload / "src" / "qml")
    return subprocess.CompletedProcess(command, 0)


def test_installer_includes_app_model_licenses_and_shortcuts(
    build_host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, binarycreator = build_host
    license_text = (PROJECT / "LICENSE").read_bytes()
    assert b"Mozilla Public License Version 2.0" in license_text

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "pyside6-deploy":
            return fake_deploy(command, **kwargs)
        assert command[0] == str(binarycreator)
        assert "--offline-only" in command
        assert kwargs["check"] is True
        config = Path(command[command.index("--config") + 1])
        settings = ElementTree.parse(config).getroot()
        assert settings.findtext("Version") == "0.1.0-alpha.1"
        assert settings.findtext("MaintenanceToolName") == "EntropyMaintenanceTool"
        assert settings.findtext("RunProgram") == "@TargetDir@/Entropy.exe"
        assert "LOCALAPPDATA" in config.with_name("controlscript.qs").read_text()
        with Image.open(config.with_name("Entropy.ico")) as icon:
            assert icon.format == "ICO"
            assert (16, 16) in icon.ico.sizes() and (256, 256) in icon.ico.sizes()
        packages = Path(command[command.index("--packages") + 1])
        component = packages / package_windows.COMPONENT
        metadata = ElementTree.parse(component / "meta" / "package.xml").getroot()
        assert metadata.findtext("Version") == "0.1.0-alpha.1"
        licenses = {
            item.attrib["name"]: item.attrib["file"]
            for item in metadata.findall("Licenses/License")
        }
        assert licenses["Mozilla Public License 2.0"] == "LICENSE"
        assert (component / "meta" / "LICENSE").read_bytes() == license_text
        assert (component / "meta" / "Real-ESRGAN.txt").is_file()
        data = component / "data"
        assert (data / "LICENSE").read_bytes() == license_text
        assert (data / "Entropy.exe").read_bytes() == b"standalone application"
        assert (data / "_mnncengine.pyd").read_bytes() == b"GPU runtime"
        assert (data / "src" / "qml" / "Main.qml").is_file()
        assert (data / "models" / "model.mnn").read_bytes() == b"verified model"
        assert (data / "models" / "model.license.txt").is_file()
        assert (
            b"GNU LESSER GENERAL PUBLIC LICENSE"
            in (data / "licenses" / "Qt" / "LGPL-3.0-only.txt").read_bytes()
        )
        assert (
            b"GNU GENERAL PUBLIC LICENSE"
            in (data / "licenses" / "Qt" / "GPL-3.0-only.txt").read_bytes()
        )
        assert b"Apache License" in (data / "licenses" / "MNN" / "LICENSE").read_bytes()
        shortcuts = (component / "meta" / "installscript.qs").read_text()
        assert "@StartMenuDir@/Entropy.lnk" in shortcuts
        assert "@DesktopDir@/Entropy.lnk" in shortcuts
        assert "@StartMenuDir@/Uninstall Entropy.lnk" in shortcuts
        assert "@TargetDir@/EntropyMaintenanceTool.exe" in shortcuts
        assert not (data / "Entropy.cmd").exists()
        Path(command[-1]).write_bytes(b"offline installer")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(package_windows.subprocess, "run", fake_run)
    installer = package_windows.package_windows(project, binarycreator=binarycreator)
    assert installer.name == "entropy-windows-x86_64-setup.exe"
    assert installer.read_bytes() == b"offline installer"
    assert not list((project / "build").iterdir())


def test_failed_deployment_does_not_publish_an_installer(
    build_host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, binarycreator = build_host

    def fail(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(package_windows.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        package_windows.package_windows(project, binarycreator=binarycreator)
    assert not list((project / "dist").iterdir())


def test_missing_standalone_executable_is_rejected(
    build_host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, binarycreator = build_host
    monkeypatch.setattr(
        package_windows.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )
    with pytest.raises(RuntimeError, match="did not produce the standalone"):
        package_windows.package_windows(project, binarycreator=binarycreator)
