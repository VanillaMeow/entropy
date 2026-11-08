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

SMOKE_TEST = """
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuickControls2 import QQuickStyle
from src.app import create_engine
from src.config import UpscaleRequest
from src.controller import AppController
from src.engine import import_mnn
from src.models import ensure_default_model

assert Path(import_mnn().__file__).resolve().is_relative_to(Path.cwd())
assert ensure_default_model().is_file()
QQuickStyle.setStyle("Material")
app = QGuiApplication([])
controller = AppController(start_setup=False)
engine = create_engine(controller)
assert engine.rootObjects(), "Packaged QML failed to load"
for window in engine.rootObjects():
    window.close()
controller.shutdown()
with TemporaryDirectory() as scratch:
    scratch = Path(scratch)
    image = scratch / "input.png"
    Image.new("RGBA", (8, 6), (100, 150, 200, 80)).save(image)
    request = UpscaleRequest(images=(image,), output_dir=scratch, output_scale=0.5)
    job = scratch / "job.json"
    job.write_text(request.model_dump_json(), encoding="utf-8")
    subprocess.run([sys.executable, "-I", "-m", "src.worker", str(job)],
                   check=True, timeout=60)
    with Image.open(scratch / "input_0.5x.png") as output:
        assert output.size == (4, 3) and output.mode == "RGBA"
print("Portable Python, MNN, QML, bundled model and worker smoke test passed.")
"""


def package_windows(project: Path) -> Path:
    """Assemble and check a relocated bundle before creating its release archive."""
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
        (bundle / "Entropy.cmd").write_bytes(LAUNCHER.replace("\n", "\r\n").encode("ascii"))

        # Relocate before checking, so paths from the build cannot hide missing files.
        relocated = staging / "portable path with spaces" / "Entropy"
        relocated.parent.mkdir()
        shutil.move(bundle, relocated)
        environment = os.environ.copy()
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        environment.update(
            PYTHONNOUSERSITE="1",
            PYTHONUTF8="1",
            LOCALAPPDATA=str(staging / "smoke-data"),
            QT_QPA_PLATFORM="offscreen",
            QT_QUICK_BACKEND="software",
            ENTROPY_MODEL_DIR=str(relocated / "models"),
        )
        subprocess.run(
            [str(relocated / "python" / "python.exe"), "-I", "-c", SMOKE_TEST],
            cwd=relocated,
            env=environment,
            check=True,
            timeout=120,
        )
        archive = shutil.make_archive(
            str(dist / "entropy-windows-x86_64"), "zip", relocated.parent, relocated.name
        )
    return Path(archive)


if __name__ == "__main__":
    print(package_windows(Path(__file__).resolve().parent.parent))
