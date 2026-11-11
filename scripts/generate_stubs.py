"""Mirror PySide6's bundled type stubs into ``typings/``, patching their gaps.

Pyright reads ``typings/`` before site-packages. Once ``typings/PySide6`` exists
it is authoritative for the whole package: PySide6's stubs reference each other
(``PySide6.QtGui.QImage`` inside QtQuick, for example), and any module missing
from the mirror would leave those references Unknown. So every stub is copied,
and a few get targeted patches.

The output is generated and not committed. Run this after ``uv sync`` and after
every PySide6 upgrade; ``--check`` reports a missing or stale mirror.
"""

import argparse
import shutil
import sys
from dataclasses import dataclass
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path

# Located without importing; PySide6 has no __init__.pyi for pyright to read
_SPEC = find_spec('PySide6')
if _SPEC is None or _SPEC.origin is None:
    msg = 'PySide6 is not installed in this environment.'
    raise SystemExit(msg)
PYSIDE = Path(_SPEC.origin).parent
TYPINGS = Path(__file__).resolve().parents[1] / 'typings' / 'PySide6'


@dataclass(frozen=True)
class Patch:
    """Replace exactly one region of a stub, from ``start`` up to ``end``."""

    reason: str
    start: str
    end: str
    replacement: str


# The bundled Property is an untyped class, so pyright sees `self.busy` as a
# Property object instead of the getter's return type
PROPERTY = Patch(
    reason='Make Property a typed descriptor',
    start='class Property:\n',
    end='class PyClassProperty(property):\n',
    replacement="""\
_PropertyT = typing.TypeVar("_PropertyT")


class Property(typing.Generic[_PropertyT]):
    fget: collections.abc.Callable[[typing.Any], _PropertyT] | None
    fset: collections.abc.Callable[[typing.Any, _PropertyT], None] | None

    def __init__(self, type: type[_PropertyT], /, fget: collections.abc.Callable[[typing.Any], _PropertyT] | None = ..., fset: collections.abc.Callable[[typing.Any, _PropertyT], None] | None = ..., freset: collections.abc.Callable[[typing.Any, typing.Any], None] | None = ..., doc: str | None = ..., notify: PySide6.QtCore.Signal | None = ..., designable: bool = ..., scriptable: bool = ..., stored: bool = ..., user: bool = ..., constant: bool = ..., final: bool = ...) -> None: ...
    def __call__(self, func: collections.abc.Callable[[typing.Any], _PropertyT], /) -> typing.Self: ...
    @typing.overload
    def __get__(self, instance: None, owner: type[typing.Any] | None, /) -> typing.Self: ...
    @typing.overload
    def __get__(self, instance: object, owner: type[typing.Any] | None = ..., /) -> _PropertyT: ...
    def __set__(self, instance: object, value: _PropertyT, /) -> None: ...
    def deleter(self, fdel: collections.abc.Callable[[typing.Any], None], /) -> typing.Self: ...
    def getter(self, fget: collections.abc.Callable[[typing.Any], _PropertyT], /) -> typing.Self: ...
    def read(self, fget: collections.abc.Callable[[typing.Any], _PropertyT], /) -> typing.Self: ...
    def setter(self, fset: collections.abc.Callable[[typing.Any, _PropertyT], None], /) -> typing.Self: ...
    def write(self, fset: collections.abc.Callable[[typing.Any, _PropertyT], None], /) -> typing.Self: ...


""",
)

# QmlUncreatable is used as a class decorator but the stub omits __call__
QML_UNCREATABLE = Patch(
    reason='Let QmlUncreatable decorate a class',
    start='class QmlUncreatable:\n',
    end='class VolatileBool:\n',
    replacement="""\
class QmlUncreatable:
    def __init__(self, reason: str, /) -> None: ...
    def __call__(self, cls: _QmlType, /) -> _QmlType: ...


""",
)

# The C++ out-parameter for the stack trace leaked into the return type; at
# runtime evaluate() returns a plain QJSValue
JS_EVALUATE = Patch(
    reason='Make QJSEngine.evaluate return QJSValue',
    start=(
        '    def evaluate(self, program: str, /, fileName: str = ..., lineNumber: int = ...) '
        '-> typing.Tuple[PySide6.QtQml.QJSValue, typing.List[str]]: ...'
    ),
    end='\n',
    replacement=(
        '    def evaluate(self, program: str, /, fileName: str = ..., lineNumber: int = ...) '
        '-> PySide6.QtQml.QJSValue: ...'
    ),
)

PATCHES = {'QtCore.pyi': (PROPERTY,), 'QtQml.pyi': (QML_UNCREATABLE, JS_EVALUATE)}


def apply(text: str, patch: Patch) -> str:
    """Apply one patch, failing loudly if PySide6's stub no longer matches it."""
    if text.count(patch.start) != 1:
        msg = f'{patch.reason}: expected one {patch.start.strip()!r} in the PySide6 stub'
        raise RuntimeError(msg)
    begin = text.index(patch.start)
    end = text.find(patch.end, begin)
    if end == -1:
        msg = f'{patch.reason}: {patch.end.strip()!r} no longer follows {patch.start.strip()!r}'
        raise RuntimeError(msg)
    return text[:begin] + patch.replacement + text[end:]


def generate(name: str) -> str:
    """Return the mirrored copy of one PySide6 stub, patched and with a provenance header."""
    patches = PATCHES.get(name, ())
    text = (PYSIDE / name).read_text(encoding='utf-8')
    for patch in patches:
        text = apply(text, patch)
    reasons = ''.join(f'#   Patched: {patch.reason}\n' for patch in patches)
    header = (
        f'# Generated by scripts/generate_stubs.py from PySide6 {version("PySide6")}. '
        f'Do not edit.\n{reasons}\n'
    )
    return header + text


def main() -> int:
    """Write the mirror, or verify it with --check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail if the overrides are stale')
    args = parser.parse_args()

    names = sorted(path.name for path in PYSIDE.glob('*.pyi'))
    if missing := sorted(set(PATCHES) - set(names)):
        msg = f'PySide6 no longer ships the patched stubs: {", ".join(missing)}'
        raise RuntimeError(msg)

    if args.check:
        mirrored = {path.name for path in TYPINGS.glob('*.pyi')}
        stale = [
            name
            for name in names
            if name not in mirrored
            or (TYPINGS / name).read_text(encoding='utf-8') != generate(name)
        ]
        if stale or mirrored - set(names):
            print(
                'The PySide6 stub mirror is missing or stale. '
                'Run: uv run python scripts/generate_stubs.py',
                file=sys.stderr,
            )
            return 1
        print('The PySide6 stub mirror is up to date.')
        return 0

    # Rebuild from scratch so stubs dropped by a PySide6 upgrade do not linger
    shutil.rmtree(TYPINGS, ignore_errors=True)
    TYPINGS.mkdir(parents=True)
    for name in names:
        (TYPINGS / name).write_text(generate(name), encoding='utf-8')
    print(f'Mirrored {len(names)} PySide6 stubs into {TYPINGS}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
