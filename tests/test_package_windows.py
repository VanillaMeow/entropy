"""Check the contents of the portable Windows archive."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from scripts import package_windows


def test_portable_archive_contains_runtime_model_and_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("Read me", encoding="utf-8")
    (project / "LICENSE").write_text("Mozilla Public License Version 2.0", encoding="utf-8")
    python_home = tmp_path / "managed-python"
    unrelated = python_home / "Lib" / "site-packages" / "unrelated"
    unrelated.mkdir(parents=True)
    (unrelated / "__init__.py").touch()
    (python_home / "python.exe").write_bytes(b"interpreter")
    (python_home / "python314.dll").write_bytes(b"Python runtime")
    redist = tmp_path / "redist"
    crt = redist / "x64" / "Microsoft.VC143.CRT"
    crt.mkdir(parents=True)
    (crt / "msvcp140.dll").write_bytes(b"MSVC runtime")
    native_root = tmp_path / "native"
    native = native_root / "gpu-runtime"
    (native / "MNN").mkdir(parents=True)
    (native / "MNN" / "__init__.py").write_bytes(b"GPU runtime")
    (native / "_mnncengine.pyd").write_bytes(b"native extension")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["check"] is True
        if command[:2] == ["uv", "export"]:
            assert "--locked" in command and "--no-dev" in command
            Path(command[-1]).touch()
        elif command[:2] == ["uv", "build"]:
            wheel_dir = Path(command[-1])
            wheel_dir.mkdir()
            (wheel_dir / "entropy-0.1.0-py3-none-any.whl").touch()
        elif command[:3] == ["uv", "pip", "install"]:
            packages = Path(command[command.index("--target") + 1])
            if "-r" in command:
                assert "--require-hashes" in command
                (packages / "PySide6").mkdir(parents=True)
                (packages / "PySide6" / "QtQml.pyd").touch()
            else:
                qml = packages / "src" / "qml"
                qml.mkdir(parents=True)
                (qml / "Main.qml").write_text("ApplicationWindow {}", encoding="utf-8")
        else:
            raise AssertionError(f"Unexpected packaging command: {command}")
        return subprocess.CompletedProcess(command, 0)

    def fake_model(*, directory: Path) -> Path:
        directory.mkdir()
        model = directory / "model.mnn"
        model.write_bytes(b"model")
        (directory / "model.license.txt").write_bytes(b"model license")
        return model

    monkeypatch.setattr(
        package_windows, "sys", SimpleNamespace(platform="win32", base_prefix=str(python_home))
    )
    monkeypatch.setattr(package_windows, "runtime_root", lambda: native_root)
    monkeypatch.setattr(
        package_windows,
        "activate_local_runtime",
        lambda: {"directory": native.name, "compiled_backends": ["OpenCL", "Vulkan"]},
    )
    monkeypatch.setattr(package_windows, "ensure_default_model", fake_model)
    monkeypatch.setattr(package_windows.subprocess, "run", fake_run)
    monkeypatch.setenv("VCTOOLSREDISTDIR", str(redist))

    archive = package_windows.package_windows(project)
    assert archive.name == "entropy-windows-x86_64.zip"
    with ZipFile(archive) as bundle:
        assert bundle.read("Entropy/LICENSE") == b"Mozilla Public License Version 2.0"
        assert bundle.read("Entropy/python/python314.dll") == b"Python runtime"
        assert bundle.read("Entropy/python/msvcp140.dll") == b"MSVC runtime"
        assert bundle.read("Entropy/python/Lib/site-packages/MNN/__init__.py") == b"GPU runtime"
        assert (
            bundle.read("Entropy/python/Lib/site-packages/_mnncengine.pyd") == b"native extension"
        )
        assert "Entropy/python/Lib/site-packages/src/qml/Main.qml" in bundle.namelist()
        assert "Entropy/python/Lib/site-packages/PySide6/QtQml.pyd" in bundle.namelist()
        assert bundle.read("Entropy/models/model.mnn") == b"model"
        assert bundle.read("Entropy/models/model.license.txt") == b"model license"
        launcher = bundle.read("Entropy/Entropy.cmd")
        assert b'"%~dp0python\\python.exe" -I -m src' in launcher
        assert b"\r\n" in launcher
        assert not any("unrelated" in name or name.endswith(".whl") for name in bundle.namelist())
    assert not list((project / "build").iterdir())
