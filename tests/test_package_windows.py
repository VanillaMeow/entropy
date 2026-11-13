"""Validate the standalone application and Qt Installer Framework packaging contract."""

import shutil
import subprocess
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from PIL import Image
from PIL.IcoImagePlugin import IcoImageFile
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QJSEngine

from scripts import package_windows

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def build_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Fake a Windows x64 build host with a project copy, Qt IFW and a GPU runtime."""
    # A space in the path catches quoting mistakes in the build commands
    project = tmp_path / 'project with spaces'
    project.mkdir()
    for filename in ('README.md', 'LICENSE'):
        shutil.copy2(PROJECT / filename, project / filename)
    for directory in ('src', 'packaging', 'flatpak'):
        shutil.copytree(
            PROJECT / directory,
            project / directory,
            ignore=shutil.ignore_patterns('__pycache__'),
        )

    binarycreator = tmp_path / 'Qt IFW' / 'binarycreator.exe'
    binarycreator.parent.mkdir()
    binarycreator.touch()

    native_root = tmp_path / 'native'
    native = native_root / 'gpu-runtime'
    (native / 'MNN').mkdir(parents=True)
    (native / 'MNN' / '__init__.py').write_text('from _mnncengine import *\n')
    (native / '_mnncengine.pyd').write_bytes(b'GPU runtime')

    monkeypatch.setattr(
        package_windows,
        'sys',
        SimpleNamespace(platform='win32', maxsize=2**63 - 1, base_prefix=str(tmp_path / 'python')),
    )
    monkeypatch.setattr(package_windows.platform, 'machine', lambda: 'AMD64')
    monkeypatch.setattr(package_windows, 'runtime_root', lambda: native_root)
    monkeypatch.setattr(
        package_windows,
        'activate_local_runtime',
        lambda: {'directory': native.name, 'compiled_backends': ['OpenCL']},
    )
    monkeypatch.setattr(package_windows, 'application_version', lambda: '0.1.0-alpha.1')
    monkeypatch.setattr(package_windows, 'distributions', lambda: ())

    def fake_model(*, directory: Path) -> Path:
        directory.mkdir()
        model = directory / 'model.mnn'
        model.write_bytes(b'verified model')
        (directory / 'model.license.txt').write_bytes(b'model license')
        return model

    monkeypatch.setattr(package_windows, 'ensure_default_model', fake_model)
    return project, binarycreator


def fake_deploy(
    command: list[str], *, cwd: Path, env: dict[str, str], check: bool
) -> subprocess.CompletedProcess[str]:
    """Check the pyside6-deploy call, then lay out a payload the way it would."""
    assert command[0] == 'pyside6-deploy'
    assert '--no-install' in command
    assert check is True

    config = ConfigParser()
    config.read(command[command.index('--config-file') + 1])
    assert config['nuitka']['mode'] == 'standalone'
    assert 'src/ui/qml/Main.qml' in config['qt']['qml_files']
    assert '--include-package=MNN' in config['nuitka']['extra_args']
    assert '--include-distribution-metadata=entropy' in config['nuitka']['extra_args']
    assert '--windows-console-mode=attach' in config['nuitka']['extra_args']
    assert '--file-version=0.1.0' in config['nuitka']['extra_args']

    # The GPU runtime has to come first on the path, so Nuitka bundles it
    native = Path(env['PYTHONPATH'].split(package_windows.os.pathsep)[0])
    assert (native / '_mnncengine.pyd').is_file()

    payload = cwd / 'frozen' / 'Entropy.dist'
    payload.mkdir(parents=True)
    (payload / 'Entropy.exe').write_bytes(b'standalone application')
    shutil.copy2(native / '_mnncengine.pyd', payload / '_mnncengine.pyd')
    shutil.copytree(cwd / 'src' / 'ui' / 'qml', payload / 'src' / 'ui' / 'qml')

    return subprocess.CompletedProcess(command, 0)


# What a finished installer layout must contain


def check_installer_config(config: Path) -> None:
    settings = ElementTree.parse(config).getroot()
    assert settings.findtext('Version') == '0.1.0-alpha.1'
    assert settings.findtext('MaintenanceToolName') == 'EntropyMaintenanceTool'
    assert settings.findtext('SupportsModify') == 'false'
    assert settings.findtext('RunProgram') == '@TargetDir@/app/Entropy.exe'

    with Image.open(config.with_name('Entropy.ico')) as icon:
        assert isinstance(icon, IcoImageFile)
        assert (16, 16) in icon.ico.sizes() and (256, 256) in icon.ico.sizes()


def check_component_metadata(component: Path, license_text: bytes) -> None:
    metadata = ElementTree.parse(component / 'meta' / 'package.xml').getroot()
    assert metadata.findtext('Version') == '0.1.0-alpha.1'

    licenses = {
        item.attrib['name']: item.attrib['file'] for item in metadata.findall('Licenses/License')
    }
    assert licenses['Mozilla Public License 2.0'] == 'LICENSE'
    assert (component / 'meta' / 'LICENSE').read_bytes() == license_text
    assert (component / 'meta' / 'Real-ESRGAN.txt').is_file()


def check_payload(data: Path, license_text: bytes) -> None:
    assert (data / 'LICENSE').read_bytes() == license_text
    assert (data / 'Entropy.exe').read_bytes() == b'standalone application'
    assert (data / '_mnncengine.pyd').read_bytes() == b'GPU runtime'
    assert (data / 'src' / 'ui' / 'qml' / 'Main.qml').is_file()
    assert (data / 'models' / 'model.mnn').read_bytes() == b'verified model'
    assert (data / 'models' / 'model.license.txt').is_file()

    licenses = data / 'licenses'
    assert (
        b'GNU LESSER GENERAL PUBLIC LICENSE' in (licenses / 'Qt' / 'LGPL-3.0-only.txt').read_bytes()
    )
    assert b'GNU GENERAL PUBLIC LICENSE' in (licenses / 'Qt' / 'GPL-3.0-only.txt').read_bytes()
    assert b'Apache License' in (licenses / 'MNN' / 'LICENSE').read_bytes()


def check_shortcuts(component: Path) -> None:
    shortcuts = (component / 'meta' / 'installscript.qs').read_text()
    assert '@StartMenuDir@/Entropy.lnk' in shortcuts
    assert '@DesktopDir@/Entropy.lnk' in shortcuts
    assert '@StartMenuDir@/Uninstall Entropy.lnk' in shortcuts
    assert '@TargetDir@/EntropyMaintenanceTool.exe' in shortcuts
    assert 'arguments=--start-uninstaller' in shortcuts
    assert '@TargetDir@/app/Entropy.exe' in shortcuts
    assert 'workingDirectory=@TargetDir@/app' in shortcuts


# Tests


def test_installer_includes_app_model_licenses_and_shortcuts(
    build_host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, binarycreator = build_host
    license_text = (PROJECT / 'LICENSE').read_bytes()
    assert b'Mozilla Public License Version 2.0' in license_text

    def fake_run(
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == 'pyside6-deploy':
            assert cwd is not None and env is not None
            return fake_deploy(command, cwd=cwd, env=env, check=check)

        # The startup check runs the real executable, headless, from its own folder
        if Path(command[0]).name == 'Entropy.exe':
            assert Path(command[0]).is_file()
            assert env is not None
            assert cwd == Path(command[0]).parent
            assert env['ENTROPY_STARTUP_CHECK'] == '1'
            assert env['QT_QPA_PLATFORM'] == 'offscreen'
            assert timeout == 30
            return subprocess.CompletedProcess(command, 0)

        # Everything else must be binarycreator, given a complete layout
        assert command[0] == str(binarycreator)
        assert '--offline-only' in command
        assert check is True

        packages = Path(command[command.index('--packages') + 1])
        component = packages / package_windows.COMPONENT
        data = component / 'data' / 'app'

        check_installer_config(Path(command[command.index('--config') + 1]))
        check_component_metadata(component, license_text)
        check_payload(data, license_text)
        check_shortcuts(component)

        # The app lives one folder down, away from the maintenance tool's Qt DLLs
        assert not (component / 'data' / 'Entropy.exe').exists()
        assert not (data / 'Entropy.cmd').exists()

        Path(command[-1]).write_bytes(b'offline installer')
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(package_windows.subprocess, 'run', fake_run)

    installer = package_windows.package_windows(project, binarycreator=binarycreator)

    assert installer.name == 'entropy-windows-x86_64-setup.exe'
    assert installer.read_bytes() == b'offline installer'
    assert not list((project / 'build').iterdir())


def test_failed_deployment_does_not_publish_an_installer(
    build_host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, binarycreator = build_host

    def fail(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(package_windows.subprocess, 'run', fail)

    with pytest.raises(subprocess.CalledProcessError):
        package_windows.package_windows(project, binarycreator=binarycreator)

    assert not list((project / 'dist').iterdir())


def test_missing_standalone_executable_is_rejected(
    build_host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, binarycreator = build_host

    # Every command succeeds but writes nothing, like a deploy that silently did no work
    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(package_windows.subprocess, 'run', fake_run)

    with pytest.raises(RuntimeError, match='did not produce the standalone'):
        package_windows.package_windows(project, binarycreator=binarycreator)


def test_failed_startup_does_not_publish_an_installer(
    build_host: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, binarycreator = build_host

    def fake_run(
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == 'pyside6-deploy':
            assert cwd is not None and env is not None
            return fake_deploy(command, cwd=cwd, env=env, check=check)

        assert Path(command[0]).name == 'Entropy.exe'
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(package_windows.subprocess, 'run', fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        package_windows.package_windows(project, binarycreator=binarycreator)

    assert not list((project / 'dist').iterdir())


@pytest.mark.parametrize('installing', [False, True])
def test_installer_skips_unneeded_pages_and_maintenance_opens_uninstaller(
    monkeypatch: pytest.MonkeyPatch, installing: bool
) -> None:
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QJSEngine(app)

    # Stand-ins for the Qt IFW globals the control script uses, recording every call
    result = engine.evaluate(
        'var calls = [];'
        'var QInstaller = {Introduction: 0x1000, ComponentSelection: 0x3000, '
        'LicenseCheck: 0x4000, StartMenuSelection: 0x5000};'
        'var installer = {'
        f'isInstaller: function() {{ return {str(installing).lower()}; }},'
        'setDefaultPageVisible: function(page, visible) { calls.push([page, visible]); },'
        "environmentVariable: function(name) { return 'C:/Users/Test User/AppData/Local'; },"
        'setValue: function(key, value) { calls.push([key, value]); },'
        "setUninstaller: function() { calls.push(['uninstall']); },"
        "setCompleteUninstallation: function(complete) { calls.push(['complete', complete]); }"
        '};'
    )
    assert not result.isError(), result.toString()

    script = PROJECT / 'packaging' / 'windows' / 'config' / 'controlscript.qs'
    result = engine.evaluate(script.read_text(), str(script))
    assert not result.isError(), result.toString()

    result = engine.evaluate('new Controller(); calls;')
    assert not result.isError(), result.toString()

    # Installing picks a per-user folder, while maintenance goes straight to uninstalling
    assert result.toVariant() == [
        [0x3000, False],
        [0x5000, False],
    ] + (
        [['TargetDir', 'C:/Users/Test User/AppData/Local/Programs/Entropy']]
        if installing
        else [['uninstall'], ['complete', True], [0x1000, False], [0x4000, False]]
    )
