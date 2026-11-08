"""Package the app, managed Python, GPU runtime and model as a portable Windows ZIP."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from src.models import ensure_default_model
from src.paths import runtime_root
from src.runtime import activate_local_runtime

LAUNCHER = """@echo off
setlocal
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "ENTROPY_MODEL_DIR=%~dp0models"
"%~dp0python\\python.exe" -I -m src %*
set "entropy_exit=%errorlevel%"
if not "%entropy_exit%"=="0" pause
exit /b %entropy_exit%
"""


def package_windows(project: Path) -> Path:
    """Assemble the portable bundle and create its release archive."""
    if sys.platform != "win32":
        raise RuntimeError("Windows packaging must run on a Windows x64 build host.")
    python_home = Path(sys.base_prefix)
    if not (python_home / "python.exe").is_file():
        raise RuntimeError("Run packaging with uv-managed Windows Python.")
    redist = os.environ.get("VCTOOLSREDISTDIR")
    if not redist:
        raise RuntimeError("Package from the x64 Native Tools Command Prompt for Visual Studio.")
    runtime_dlls = list(Path(redist).glob("x64/Microsoft.VC*.CRT/*.dll"))
    if not runtime_dlls:
        raise RuntimeError("The MSVC x64 redistributable DLLs could not be found.")
    metadata = activate_local_runtime()
    if metadata is None or set(metadata.get("compiled_backends", [])) != {"OpenCL", "Vulkan"}:
        raise RuntimeError("Build the OpenCL/Vulkan runtime with scripts/build_mnn.py first.")
    native = runtime_root() / metadata["directory"]
    build = project / "build"
    build.mkdir(exist_ok=True)
    dist = project / "dist"
    dist.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="windows-", dir=build) as temporary:
        staging = Path(temporary)
        bundle = staging / "Entropy"
        python = bundle / "python" / "python.exe"
        packages = bundle / "python" / "Lib" / "site-packages"
        shutil.copytree(
            python_home,
            python.parent,
            ignore=shutil.ignore_patterns("__pycache__", "site-packages"),
        )
        for dll in runtime_dlls:
            shutil.copy2(dll, python.parent / dll.name)
        requirements = staging / "requirements.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--output-file",
                str(requirements),
            ],
            cwd=project,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--target",
                str(packages),
                "--require-hashes",
                "--only-binary",
                ":all:",
                "-r",
                str(requirements),
            ],
            check=True,
        )
        wheels = staging / "wheels"
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(wheels)], cwd=project, check=True
        )
        (wheel,) = wheels.glob("*.whl")
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--target",
                str(packages),
                "--no-deps",
                str(wheel),
            ],
            check=True,
        )
        shutil.copytree(native, packages, dirs_exist_ok=True)
        ensure_default_model(directory=bundle / "models")
        shutil.copy2(project / "README.md", bundle / "README.md")
        shutil.copy2(project / "LICENSE", bundle / "LICENSE")
        (bundle / "Entropy.cmd").write_bytes(LAUNCHER.replace("\n", "\r\n").encode("ascii"))

        archive = shutil.make_archive(
            str(dist / "entropy-windows-x86_64"), "zip", staging, bundle.name
        )
    return Path(archive)


if __name__ == "__main__":
    print(package_windows(Path(__file__).resolve().parent.parent))
