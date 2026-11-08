"""Runtime activation must stay inside the per-ABI installation directory."""

import json
import sys
from pathlib import Path

import pytest

from src import runtime


def test_no_local_runtime_leaves_import_path_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "runtime_root", lambda: tmp_path)
    before = sys.path.copy()
    assert runtime.activate_local_runtime() is None
    assert sys.path == before


def test_compiled_app_uses_its_bundled_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "is_compiled", lambda: True)
    monkeypatch.setattr(
        runtime,
        "runtime_root",
        lambda: pytest.fail("Installed apps must not load user-built runtimes"),
    )
    before = sys.path.copy()
    assert runtime.activate_local_runtime() is None
    assert sys.path == before


@pytest.mark.parametrize("directory", ["..", ".", "", "../outside", "/tmp/outside"])
def test_manifest_cannot_escape_runtime_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory: str
) -> None:
    monkeypatch.setattr(runtime, "runtime_root", lambda: tmp_path)
    (tmp_path / "active.json").write_text(json.dumps({"directory": directory}))
    with pytest.raises(ValueError, match="Invalid local MNN runtime path"):
        runtime.activate_local_runtime()


def test_incomplete_runtime_is_not_activated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "runtime_root", lambda: tmp_path)
    (tmp_path / "active.json").write_text('{"directory": "missing"}')
    with pytest.raises(ValueError, match="incomplete"):
        runtime.activate_local_runtime()
