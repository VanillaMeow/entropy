"""Build MNN with OpenCL and install it as a per-user runtime.

Run from the project root with ``uv run python scripts/build_mnn.py``.

PyPI's MNN wheels are CPU-only, so this builds the Python bindings from a
pinned source checkout, the same way upstream's
``pymnn/pip_package/build_deps.py`` does but with every step checked. The
result is installed into the user's data directory; neither the system nor the
project's virtual environment is modified.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from entropy.paths import cache_dir, runtime_root

if TYPE_CHECKING:
    from collections.abc import Sequence

MNN_VERSION = '3.6.2'
MNN_COMMIT = '7e3c6fb5225d3ccf22807ee641332669df34650d'
MNN_REPOSITORY = 'https://github.com/alibaba/MNN.git'

PATCHES = sorted((Path(__file__).resolve().parents[1] / 'packaging' / 'mnn').glob('*.patch'))
WINDOWS = sys.platform == 'win32'
NOEXECSTACK = '-Wl,-z,noexecstack'

# Upstream's setup.py still imports distutils, so pin the setuptools that provides it
WHEEL_BUILD_REQUIREMENTS = ('setuptools==84.2.1', 'wheel==0.48.0', 'numpy>=2.5.4,<3')

# Why some options are needed:
#   CMAKE_POLICY_VERSION_MINIMUM: CMake 4 rejects old minimums in bundled projects
#   CMAKE_CXX_EXTENSIONS: MNN forces __STRICT_ANSI__, which GCC 16 needs this off for
#   MNN_BUILD_TRAIN, OPENCV, IMGCODECS, AUDIO: the Python package imports them all
CMAKE_OPTIONS = (
    '-DCMAKE_BUILD_TYPE=Release',
    '-DMNN_BUILD_SHARED_LIBS=OFF',
    '-DMNN_OPENCL=ON',
    '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
    '-DCMAKE_CXX_EXTENSIONS=OFF',
    '-DMNN_BUILD_TRAIN=ON',
    '-DMNN_BUILD_OPENCV=ON',
    '-DMNN_IMGCODECS=ON',
    '-DMNN_BUILD_AUDIO=ON',
)

# MSVC throughout, with the static /MT runtime that upstream's setup.py compiles with
WINDOWS_CMAKE_OPTIONS = (
    '-DCMAKE_C_COMPILER=cl',
    '-DCMAKE_CXX_COMPILER=cl',
    '-DMNN_WIN_RUNTIME_MT=ON',
)

# Hand-written assembly would otherwise mark the extension as needing an
# executable stack, which current glibc refuses to load
LINUX_CMAKE_OPTIONS = (
    f'-DCMAKE_EXE_LINKER_FLAGS={NOEXECSTACK}',
    f'-DCMAKE_SHARED_LINKER_FLAGS={NOEXECSTACK}',
)


def run(
    command: Sequence[str | Path], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Echo and run a command, raising if it fails."""
    arguments = [str(argument) for argument in command]

    print('+ ' + ' '.join(arguments), flush=True)
    subprocess.run(arguments, cwd=cwd, env=env, check=True)


def succeeds(command: Sequence[str | Path], *, cwd: Path | None = None) -> bool:
    """Run a command quietly and report whether it exited successfully."""
    result = subprocess.run(
        [str(argument) for argument in command], cwd=cwd, capture_output=True, check=False
    )
    return result.returncode == 0


def parse_args() -> argparse.Namespace:
    """Parse the command line and stop early if the host cannot build MNN."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--jobs',
        type=int,
        default=min(8, os.cpu_count() or 2),
        help='parallel compile jobs (default: %(default)s)',
    )
    parser.add_argument(
        '--source', type=Path, help='reuse an existing MNN checkout at the pinned commit'
    )
    args = parser.parse_args()

    if args.jobs < 1:
        parser.error('--jobs must be positive')

    if sys.platform not in {'linux', 'win32'}:
        parser.error('Only Linux and Windows are supported; macOS is not yet supported.')

    # Check every tool up front instead of failing halfway through a long build
    tools = ['uv', 'git', 'cmake', 'ninja', *(('cl', 'link', 'rc') if WINDOWS else ('c++',))]
    if missing := [tool for tool in tools if shutil.which(tool) is None]:
        hint = ''
        if WINDOWS:
            hint = (
                ' Install Visual Studio Build Tools with "Desktop development with C++" and a'
                ' Windows SDK, then run from the x64 Native Tools Command Prompt.'
            )
        parser.error(f'Missing build tools: {", ".join(missing)}.{hint}')

    # MNN's Windows build only supports x64, and mixing architectures fails at link time
    if WINDOWS:
        x64_python = platform.machine().lower() in {'amd64', 'x86_64'} and sys.maxsize > 2**32
        x64_toolchain = os.environ.get('VSCMD_ARG_TGT_ARCH', 'x64').lower() == 'x64'
        if not (x64_python and x64_toolchain):
            parser.error(
                'Windows builds need x64 Python, run from the x64 Native Tools Command Prompt.'
            )

    return args


def prepare_source(source: Path) -> None:
    """Clone MNN if needed, check it is the pinned commit, and apply local patches."""
    if not source.exists():
        # Keep LF line endings on Windows so the patches apply
        clone = ['git', 'clone', '--config', 'core.autocrlf=false', '--depth', '1']
        run([*clone, '--branch', MNN_VERSION, MNN_REPOSITORY, source])

    # A reused checkout could be at any commit, and the patches only fit this one
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if commit != MNN_COMMIT:
        msg = f'{source} is at {commit}, expected MNN {MNN_VERSION} ({MNN_COMMIT})'
        raise RuntimeError(msg)

    # A patch that only applies in reverse is already in place from an earlier build
    for patch in PATCHES:
        if succeeds(['git', 'apply', '--check', patch], cwd=source):
            run(['git', 'apply', patch], cwd=source)
        elif not succeeds(['git', 'apply', '--check', '--reverse', patch], cwd=source):
            msg = f'{patch.name} does not apply to {source}'
            raise RuntimeError(msg)


def build_python(cache: Path) -> Path:
    """Return a uv-managed Python with the packages upstream's setup.py needs.

    uv-managed Pythons ship development headers, which many OS installs lack,
    and a separate environment keeps setuptools out of the project's venv.
    """
    version = f'{sys.version_info.major}.{sys.version_info.minor}'
    environment = cache / f'build-env-{version}'
    python = environment / ('Scripts/python.exe' if WINDOWS else 'bin/python')

    if not python.is_file():
        run(['uv', 'venv', '--python', version, '--managed-python', environment])
    run(['uv', 'pip', 'install', '--python', python, *WHEEL_BUILD_REQUIREMENTS])
    return python


def build_wheel(source: Path, python: Path, jobs: int) -> Path:
    """Compile static MNN with OpenCL and package the Python bindings as a wheel."""
    # Upstream's setup.py expects the CMake tree at exactly this path
    build = source / 'pymnn_build'
    options = [*CMAKE_OPTIONS, *(WINDOWS_CMAKE_OPTIONS if WINDOWS else LINUX_CMAKE_OPTIONS)]
    run(['cmake', '-S', source, '-B', build, '-G', 'Ninja', *options])
    run(['cmake', '--build', build, '--target', 'MNN', '--parallel', str(jobs)])

    # Clear old wheels so the one found below is from this build
    package = source / 'pymnn' / 'pip_package'
    dist = package / 'dist'
    shutil.rmtree(dist, ignore_errors=True)

    env = os.environ.copy()
    if WINDOWS:
        # Make setuptools use the MSVC environment that CMake used
        env['DISTUTILS_USE_SDK'] = '1'
    else:
        env['LDFLAGS'] = NOEXECSTACK

    setup = [python, 'setup.py', 'build_ext', '--force', 'bdist_wheel', '--deps', 'opencl']
    run(setup, cwd=package, env=env)

    wheels = list(dist.glob('mnn_opencl-*.whl'))
    if len(wheels) != 1:
        msg = f'Expected one mnn_opencl wheel in {dist}, found {len(wheels)}'
        raise RuntimeError(msg)

    return wheels[0]


def install_runtime(wheel: Path, root: Path) -> Path:
    """Install the wheel into a new runtime directory and check that it imports.

    A fresh directory means a running app, which may hold the old extension
    open on Windows, never sees a half-replaced runtime.
    """
    target = root / f'mnn-{MNN_VERSION}-{uuid4().hex[:12]}'
    install = ['uv', 'pip', 'install', '--python', sys.executable, '--no-deps']
    run([*install, '--target', target, wheel])

    # Import from the new directory only, so a stale MNN elsewhere cannot pass the test
    smoke_test = (
        'import sys; sys.path.insert(0, sys.argv[1]); '
        'import MNN, MNN.expr, MNN.nn; '
        'assert MNN.__file__.startswith(sys.argv[1]), MNN.__file__'
    )
    run([sys.executable, '-c', smoke_test, target])

    return target


def activate_runtime(root: Path, target: Path) -> None:
    """Point the app at the new runtime by atomically replacing active.json."""
    manifest = {
        'directory': target.name,
        'version': MNN_VERSION,
        'source_commit': MNN_COMMIT,
        'compiled_backends': ['OpenCL'],
    }

    # Write beside the real file and rename over it, so the app never reads half a manifest
    temporary = root / f'.active-{uuid4().hex}.json'
    temporary.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    temporary.replace(root / 'active.json')


def remove_stale_runtimes(root: Path, active: Path) -> None:
    """Delete runtimes from earlier builds, leaving any that are still in use."""
    for path in root.glob('mnn-*'):
        if path == active or not path.is_dir():
            continue
        try:
            shutil.rmtree(path)
        except OSError as exc:
            print(f'Could not remove old runtime {path}, it will be retried next build: {exc}')

    # Manifests left behind by a build that was interrupted mid-write
    for leftover in root.glob('.active-*.json'):
        leftover.unlink(missing_ok=True)


def main() -> None:
    """Build, install and activate the OpenCL runtime."""
    args = parse_args()

    cache = cache_dir() / f'mnn-{MNN_VERSION}'
    cache.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve() if args.source else cache / 'source'

    prepare_source(source)
    python = build_python(cache)
    wheel = build_wheel(source, python, args.jobs)

    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    target = install_runtime(wheel, root)
    activate_runtime(root, target)
    remove_stale_runtimes(root, target)

    print(f'OpenCL MNN runtime installed in {target}')
    print('Restart the app, or click Retry setup in Diagnostics.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f'GPU runtime build failed: {exc}')
