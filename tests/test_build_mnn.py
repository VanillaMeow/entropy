"""Exercise native build orchestration without downloading or compiling MNN."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import build_mnn


@pytest.mark.parametrize("platform_name", ["linux", "win32"])
@pytest.mark.parametrize("install_fails", [False, True])
def test_build_activates_runtime_only_after_successful_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform_name: str, install_fails: bool
) -> None:
    source = tmp_path / "MNN source with spaces"
    package = source / "pymnn" / "pip_package"
    package.mkdir(parents=True)
    root = tmp_path / "runtime"
    root.mkdir()
    previous = {"directory": "previous-runtime"}
    (root / "active.json").write_text(json.dumps(previous), encoding="utf-8")
    cache = tmp_path / "cache"
    windows = platform_name == "win32"
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    build_env = cache / f"mnn-{build_mnn.MNN_VERSION}" / f"build-env-{version}"
    python = build_env / "Scripts" / "python.exe" if windows else build_env / "bin" / "python"
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []
    patched: list[Path] = []

    def fake_run(
        command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
    ) -> None:
        calls.append((command, cwd, env))
        if command[:2] == ["uv", "venv"]:
            python.parent.mkdir(parents=True)
            python.touch()
        elif "setup.py" in command:
            assert command[0] == str(python) and python.is_file()
            assert cwd == package
            wheel_dir = package / "dist"
            wheel_dir.mkdir()
            (wheel_dir / "mnn_vulkan_opencl-test.whl").touch()
        elif command[:3] == ["uv", "pip", "install"] and "--target" in command:
            if install_fails:
                raise subprocess.CalledProcessError(1, command)
            assert Path(command[-1]).is_file()
            target = Path(command[command.index("--target") + 1])
            (target / "MNN").mkdir(parents=True)
            (target / "MNN" / "__init__.py").touch()

    monkeypatch.setattr(sys, "argv", ["build_mnn.py", "--source", str(source), "--jobs", "2"])
    monkeypatch.setattr(
        build_mnn,
        "sys",
        SimpleNamespace(
            platform=platform_name,
            executable=sys.executable,
            version_info=sys.version_info,
            maxsize=2**63 - 1,
        ),
    )
    monkeypatch.setattr(build_mnn.platform, "machine", lambda: "AMD64")
    monkeypatch.delenv("VSCMD_ARG_TGT_ARCH", raising=False)
    monkeypatch.delenv("LDFLAGS", raising=False)
    monkeypatch.setattr(build_mnn.shutil, "which", lambda name: name)
    monkeypatch.setattr(build_mnn, "user_cache_path", lambda *_args, **_kwargs: cache)
    monkeypatch.setattr(build_mnn, "runtime_root", lambda: root)
    monkeypatch.setattr(build_mnn, "patch_linux_loaders", patched.append)
    monkeypatch.setattr(
        build_mnn.subprocess, "check_output", lambda *_args, **_kwargs: build_mnn.MNN_COMMIT
    )
    monkeypatch.setattr(build_mnn, "run", fake_run)

    if install_fails:
        with pytest.raises(subprocess.CalledProcessError):
            build_mnn.main()
        assert json.loads((root / "active.json").read_text()) == previous
        assert not list(root.glob(".active-*.json"))
    else:
        assert build_mnn.main() == 0
        metadata = json.loads((root / "active.json").read_text())
        assert (root / metadata["directory"] / "MNN" / "__init__.py").is_file()
        assert metadata["compiled_backends"] == ["OpenCL", "Vulkan"]
        assert metadata["linux_runtime_sonames"] is not windows
        assert metadata["source_commit"] == build_mnn.MNN_COMMIT

    configure = next(command for command, _, _ in calls if command[:2] == ["cmake", "-S"])
    assert "-DMNN_OPENCL=ON" in configure and "-DMNN_VULKAN=ON" in configure
    build = next(command for command, _, _ in calls if command[:2] == ["cmake", "--build"])
    assert build[-2:] == ["--parallel", "2"]
    wheel_env = next(env for command, _, env in calls if "setup.py" in command)
    assert wheel_env is not None
    if windows:
        assert patched == []
        assert "-DMNN_WIN_RUNTIME_MT=ON" in configure
        assert "-DCMAKE_C_COMPILER=cl" in configure
        assert "-DCMAKE_CXX_COMPILER=cl" in configure
        assert all("noexecstack" not in option for option in configure)
        assert "LDFLAGS" not in wheel_env
        assert wheel_env["DISTUTILS_USE_SDK"] == "1"
    else:
        assert patched == [source]
        assert "-DMNN_WIN_RUNTIME_MT=ON" not in configure
        assert "-DCMAKE_EXE_LINKER_FLAGS=-Wl,-z,noexecstack" in configure
        assert wheel_env["LDFLAGS"] == "-Wl,-z,noexecstack"


@pytest.mark.parametrize("missing_tool", ["cl", "link", "rc"])
def test_windows_requires_initialized_msvc_toolchain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], missing_tool: str
) -> None:
    monkeypatch.setattr(sys, "argv", ["build_mnn.py"])
    monkeypatch.setattr(build_mnn, "sys", SimpleNamespace(platform="win32", maxsize=2**63 - 1))
    monkeypatch.setattr(build_mnn.platform, "machine", lambda: "AMD64")
    monkeypatch.delenv("VSCMD_ARG_TGT_ARCH", raising=False)
    monkeypatch.setattr(
        build_mnn.shutil, "which", lambda name: None if name == missing_tool else name
    )
    with pytest.raises(SystemExit) as exc:
        build_mnn.main()
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert f"tool is missing: {missing_tool}" in error
    assert "x64 Native Tools Command Prompt" in error


def test_windows_rejects_wrong_toolchain_architecture(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["build_mnn.py"])
    monkeypatch.setattr(build_mnn, "sys", SimpleNamespace(platform="win32", maxsize=2**63 - 1))
    monkeypatch.setattr(build_mnn.platform, "machine", lambda: "AMD64")
    monkeypatch.setenv("VSCMD_ARG_TGT_ARCH", "x86")
    with pytest.raises(SystemExit) as exc:
        build_mnn.main()
    assert exc.value.code == 2
    assert "x64 Native Tools Command Prompt" in capsys.readouterr().err


def test_macos_is_not_enabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["build_mnn.py"])
    monkeypatch.setattr(build_mnn, "sys", SimpleNamespace(platform="darwin"))
    with pytest.raises(SystemExit) as exc:
        build_mnn.main()
    assert exc.value.code == 2
    assert "macOS is not yet supported" in capsys.readouterr().err
