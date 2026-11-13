"""Build a standalone Windows app with pyside6-deploy and an offline Qt IFW installer."""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
from configparser import ConfigParser
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from entropy.core.models import ensure_default_model
from entropy.paths import runtime_root
from entropy.version import application_version
from entropy.worker.runtime import activate_local_runtime

COMPONENT = 'io.github.jedace07.Entropy'

# Windows picks the closest of these for the taskbar, title bar and shortcuts
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

# The script Nuitka compiles into Entropy.exe
ENTRY_POINT = '''\
"""Compiled Entropy entry point."""

from entropy.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
'''


def create_icon(source: Path, destination: Path) -> None:
    """Render the existing app artwork into a Windows icon at multiple sizes."""
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        msg = f'Invalid application icon: {source}'
        raise RuntimeError(msg)

    # Render once at the largest size, Pillow scales it down for the rest
    image = QImage(256, 256, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    Image.frombytes('RGBA', (256, 256), bytes(image.bits())).save(
        destination, sizes=[(size, size) for size in ICON_SIZES]
    )


def _is_license_file(parts: tuple[str, ...], name: str) -> bool:
    """Whether a distribution file is a license, a notice, or the package metadata."""
    return (
        any(part.lower() in {'license', 'licenses'} for part in parts)
        or name.lower().startswith(('license', 'copying', 'notice'))
        or name == 'METADATA'
    )


def copy_dependency_licenses(destination: Path) -> None:
    """Preserve installed dependencies' license and notice files in the payload."""
    for distribution in distributions():
        for entry in distribution.files or ():
            # Paths outside the distribution's own folder are not its license files
            if '..' in entry.parts or not _is_license_file(entry.parts, entry.name):
                continue

            # locate_file() is typed as a minimal path protocol, it is a real path here
            source = Path(str(distribution.locate_file(entry)))
            if source.is_file():
                target = destination / distribution.metadata['Name'] / entry
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    # The interpreter is bundled too, so its license comes along
    for license_file in Path(sys.base_prefix).glob('LICENSE*'):
        if license_file.is_file():
            target = destination / 'Python' / license_file.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(license_file, target)


def write_deploy_spec(staging: Path) -> Path:
    """Write the pyside6-deploy configuration for a standalone Nuitka build."""
    # Windows version fields only take numbers, so drop the pre-release suffix
    release_version = application_version().split('-', 1)[0]

    qml_files = ','.join(
        path.relative_to(staging).as_posix()
        for path in sorted((staging / 'entropy' / 'ui' / 'qml').rglob('*.qml'))
    )

    # MNN loads its native module by name, which Nuitka cannot see on its own
    nuitka_arguments = [
        '--assume-yes-for-downloads',
        '--msvc=latest',
        '--windows-console-mode=attach',
        '--include-package=MNN',
        '--include-module=_mnncengine',
        '--include-distribution-metadata=entropy',
        '--product-name=Entropy',
        '--company-name=jedace07',
        '--file-description=Entropy image upscaler',
        f'--file-version={release_version}',
        f'--product-version={release_version}',
    ]

    config = ConfigParser()
    config.read_dict(
        {
            'app': {
                'title': 'Entropy',
                'project_dir': '.',
                'input_file': 'Entropy.py',
                'exec_directory': 'frozen',
                'project_file': '',
                'icon': 'Entropy.ico',
            },
            'python': {'packages': 'Nuitka'},
            'qt': {
                'qml_files': qml_files,
                'excluded_qml_plugins': '',
                'modules': 'Core,Gui,Qml,Quick,QuickControls2,Network,Svg',
                'plugins': '',
            },
            'nuitka': {'mode': 'standalone', 'extra_args': shlex.join(nuitka_arguments)},
        }
    )

    spec = staging / 'pysidedeploy.spec'
    with spec.open('w', encoding='utf-8') as stream:
        config.write(stream)

    return spec


def deploy_application(project: Path, staging: Path, native: Path) -> Path:
    """Compile an isolated source tree while making the GPU-enabled MNN importable."""
    # Build from a copy, pyside6-deploy writes its output next to the sources
    shutil.copytree(
        project / 'src' / 'entropy',
        staging / 'entropy',
        ignore=shutil.ignore_patterns('__pycache__'),
    )
    (staging / 'Entropy.py').write_text(ENTRY_POINT, encoding='utf-8')
    create_icon(project / 'flatpak' / f'{COMPONENT}.svg', staging / 'Entropy.ico')
    spec = write_deploy_spec(staging)

    # Put the local OpenCL MNN first, so Nuitka bundles it instead of the CPU-only wheel
    environment = os.environ.copy()
    environment['PYTHONPATH'] = os.pathsep.join(
        filter(None, (str(native), environment.get('PYTHONPATH')))
    )
    subprocess.run(
        ['pyside6-deploy', '--config-file', str(spec), '--force', '--no-install'],
        cwd=staging,
        env=environment,
        check=True,
    )

    payload = staging / 'frozen' / 'Entropy.dist'
    if not (payload / 'Entropy.exe').is_file():
        msg = 'pyside6-deploy did not produce the standalone Entropy.exe.'
        raise RuntimeError(msg)

    # Everything the app needs at runtime besides the compiled code
    shutil.copy2(staging / 'Entropy.ico', payload / 'Entropy.ico')
    ensure_default_model(directory=payload / 'models')
    for filename in ('README.md', 'LICENSE'):
        shutil.copy2(project / filename, payload / filename)

    copy_dependency_licenses(payload / 'licenses')
    shutil.copytree(
        project / 'packaging' / 'windows' / 'licenses', payload / 'licenses', dirs_exist_ok=True
    )

    # Start the real executable once, so a missing Qt plugin or QML file fails the build
    check_environment = environment.copy()
    check_environment['ENTROPY_STARTUP_CHECK'] = '1'
    check_environment['QT_QPA_PLATFORM'] = 'offscreen'
    subprocess.run(
        [str(payload / 'Entropy.exe')],
        cwd=payload,
        env=check_environment,
        timeout=30,
        check=True,
    )

    return payload


def _require_build_host(binarycreator: Path) -> Path:
    """Check the host and inputs, and return the OpenCL runtime to bundle."""
    if (
        sys.platform != 'win32'
        or sys.maxsize <= 2**32
        or platform.machine().lower() not in {'amd64', 'x86_64'}
    ):
        msg = 'Windows packaging must run on a Windows x64 build host.'
        raise RuntimeError(msg)

    if not binarycreator.is_file():
        msg = f'Qt Installer Framework binarycreator was not found: {binarycreator}'
        raise RuntimeError(msg)

    metadata = activate_local_runtime()
    if metadata is None or set(metadata.get('compiled_backends', [])) != {'OpenCL'}:
        msg = 'Build the OpenCL runtime with scripts/build_mnn.py first.'
        raise RuntimeError(msg)

    return runtime_root() / metadata['directory']


def _lay_out_installer(project: Path, staging: Path, payload: Path) -> Path:
    """Arrange the Qt IFW config and package folders around the payload."""
    layout = staging / 'installer'
    shutil.copytree(project / 'packaging' / 'windows', layout)
    component = layout / 'packages' / COMPONENT

    # Keep the application's Qt DLLs away from the Qt IFW maintenance tool
    (component / 'data').mkdir()
    shutil.move(str(payload), component / 'data' / 'app')

    # Shown by the installer itself, before anything is installed
    shutil.copy2(staging / 'Entropy.ico', layout / 'config' / 'Entropy.ico')
    shutil.copy2(project / 'LICENSE', component / 'meta' / 'LICENSE')
    shutil.copy2(
        project / 'src' / 'entropy' / 'licenses' / 'Real-ESRGAN.txt',
        component / 'meta' / 'Real-ESRGAN.txt',
    )

    for metadata_file in (layout / 'config' / 'config.xml', component / 'meta' / 'package.xml'):
        content = metadata_file.read_text(encoding='utf-8')
        content = content.replace('@VERSION@', application_version()).replace(
            '@RELEASE_DATE@', datetime.now(UTC).date().isoformat()
        )
        metadata_file.write_text(content, encoding='utf-8')

    return layout


def package_windows(project: Path, *, binarycreator: Path) -> Path:
    """Create a per-user installer containing the app, GPU runtime and model."""
    native = _require_build_host(binarycreator)

    project = project.resolve()
    build = project / 'build'
    build.mkdir(exist_ok=True)
    dist = project / 'dist'
    dist.mkdir(exist_ok=True)
    installer = dist / 'entropy-windows-x86_64-setup.exe'

    # Work in a scratch folder so a failed build never leaves an installer in dist
    with TemporaryDirectory(prefix='windows-', dir=build) as temporary:
        staging = Path(temporary)
        payload = deploy_application(project, staging, native)
        layout = _lay_out_installer(project, staging, payload)

        output = staging / installer.name
        subprocess.run(
            [
                str(binarycreator.resolve()),
                '--offline-only',
                '--config',
                str(layout / 'config' / 'config.xml'),
                '--packages',
                str(layout / 'packages'),
                str(output),
            ],
            check=True,
        )
        if not output.is_file():
            msg = 'Qt Installer Framework did not produce the Windows installer.'
            raise RuntimeError(msg)

        shutil.move(str(output), installer)

    return installer


def main() -> int:
    """Build the installer using a Qt IFW binarycreator supplied by CI or the developer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--binarycreator',
        type=Path,
        default=os.environ.get('QTIFW_BINARYCREATOR') or shutil.which('binarycreator'),
        help='Qt IFW binarycreator.exe path (or set QTIFW_BINARYCREATOR / PATH)',
    )
    arguments = parser.parse_args()

    if arguments.binarycreator is None:
        parser.error(
            'Install Qt Installer Framework and supply --binarycreator or QTIFW_BINARYCREATOR.'
        )

    project = Path(__file__).resolve().parent.parent
    print(package_windows(project, binarycreator=arguments.binarycreator))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
