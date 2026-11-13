"""Generate Python QML type metadata and lint the Qt Quick component tree."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QLibraryInfo


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


def main() -> int:
    """Update tooling metadata, or verify it in CI with --check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if generated types are stale')
    parser.add_argument('--format', action='store_true', help='Format QML source files in place')
    options = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    package = project / 'src'
    qml = package / 'ui' / 'qml'
    foreign = (
        Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PrefixPath))
        / 'metatypes'
        / 'qt6core_metatypes.json'
    )
    destination = qml / 'Upscaler' / 'Backend' / 'backend.qmltypes'
    with TemporaryDirectory(prefix='upscaler-qml-types-') as directory:
        temporary = Path(directory)
        meta = temporary / 'controller.json'
        generated = temporary / 'backend.qmltypes'
        subprocess.run(
            [
                'pyside6-metaobjectdump',
                '-o',
                str(meta),
                str(package / 'ui' / 'controller.py'),
            ],
            check=True,
        )
        use_double_for_float(meta)
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
        content = generated.read_text(encoding='utf-8').replace(str(project) + '/', '')
        if options.check:
            if destination.read_text(encoding='utf-8') != content:
                parser.exit(1, 'QML types are stale. Run: uv run python scripts/check_qml.py\n')
        else:
            destination.write_text(content, encoding='utf-8')
    sources = sorted(qml.glob('*.qml')) + sorted((qml / 'components').glob('*.qml'))
    if options.format:
        subprocess.run(['pyside6-qmlformat', '-i', '-W', '100', *map(str, sources)], check=True)
    # A singleton is checked through its importing components, where qmldir
    # supplies its singleton identity. Linting it as a standalone entry point
    # produces a spurious "not declared as singleton" diagnostic outside its module.
    entries = [path for path in sources if path.name != 'Theme.qml']
    subprocess.run(['pyside6-qmllint', '-I', str(qml), *map(str, entries)], check=True)
    print('QML types and component checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
