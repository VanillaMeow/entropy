"""Generate Python QML type metadata and lint the Qt Quick component tree."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QLibraryInfo

PROJECT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT / 'src' / 'entropy'
CONTROLLER = PACKAGE / 'ui' / 'controller.py'
QML = PACKAGE / 'ui' / 'qml'
QMLTYPES = QML / 'Upscaler' / 'Backend' / 'backend.qmltypes'


def use_double_for_float(meta: Path) -> None:
    """Record ``Property(float)`` as the ``double`` that PySide registers at runtime.

    metaobjectdump copies the Python type name, so QML tooling would otherwise
    see a C++ float and reject bindings to QML ``real`` properties.
    """
    dump = json.loads(meta.read_text(encoding='utf-8'))

    for module in dump:
        for cls in module['classes']:
            for prop in cls['properties']:
                if prop['type'] == 'float':
                    prop['type'] = 'double'

    meta.write_text(json.dumps(dump), encoding='utf-8')


def generate_qmltypes() -> str:
    """Describe the controller to QML tooling, the way Qt would for a C++ type."""
    # QObject and friends are described by Qt's own metatypes
    foreign = (
        Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PrefixPath))
        / 'metatypes'
        / 'qt6core_metatypes.json'
    )

    with TemporaryDirectory(prefix='upscaler-qml-types-') as directory:
        temporary = Path(directory)
        meta = temporary / 'controller.json'
        generated = temporary / 'backend.qmltypes'

        subprocess.run(['pyside6-metaobjectdump', '-o', str(meta), str(CONTROLLER)], check=True)
        use_double_for_float(meta)

        # The registrar also writes C++ registration code, which is not needed here
        subprocess.run(
            [
                'pyside6-qmltyperegistrar',
                '--generate-qmltypes=' + str(generated),
                '--import-name=Upscaler.Backend',
                '--major-version=1',
                '--minor-version=0',
                '--foreign-types=' + str(foreign),
                str(meta),
                '-o',
                str(temporary / 'unused.cpp'),
            ],
            check=True,
        )

        # Drop the absolute project path so the file is the same on every machine
        return generated.read_text(encoding='utf-8').replace(str(PROJECT) + '/', '')


def main() -> int:
    """Update tooling metadata, or verify it in CI with --check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if generated types are stale')
    parser.add_argument('--format', action='store_true', help='Format QML source files in place')
    options = parser.parse_args()

    content = generate_qmltypes()
    if not options.check:
        QMLTYPES.write_text(content, encoding='utf-8')
    elif QMLTYPES.read_text(encoding='utf-8') != content:
        parser.exit(1, 'QML types are stale. Run: uv run python scripts/check_qml.py\n')

    sources = sorted(QML.glob('*.qml')) + sorted((QML / 'components').glob('*.qml'))
    if options.format:
        subprocess.run(['pyside6-qmlformat', '-i', '-W', '100', *map(str, sources)], check=True)

    # The Theme singleton is checked through the components that import it. Linted on
    # its own, outside its module, it gets a spurious "not declared as singleton" error
    entries = [path for path in sources if path.name != 'Theme.qml']
    subprocess.run(['pyside6-qmllint', '-I', str(QML), *map(str, entries)], check=True)

    print('QML types and component checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
