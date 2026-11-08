"""Build and install a per-user MNN 3.6.2 runtime with OpenCL and Vulkan.

Run from the project with ``uv run python scripts/build_mnn.py``. Nothing is
installed system-wide or into the application's uv-managed site-packages.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from platformdirs import user_cache_path

from src.paths import runtime_root

MNN_VERSION = "3.6.2"
MNN_COMMIT = "7e3c6fb5225d3ccf22807ee641332669df34650d"


def patch_linux_loaders(source: Path) -> None:
    """Use runtime SONAMEs, avoiding a dependency on development-package symlinks."""
    patches = (
        (
            "source/backend/opencl/core/runtime/OpenCLWrapper.cpp",
            "#elif defined(__linux__)\n",
            '#elif defined(__linux__)\n        "libOpenCL.so.1",\n',
        ),
        (
            "source/backend/vulkan/runtime/vulkan_wrapper.cpp",
            '"libvulkan.so",',
            '"libvulkan.so.1",\n    "libvulkan.so",',
        ),
    )
    for relative, original, replacement in patches:
        path = source / relative
        content = path.read_text(encoding="utf-8")
        if replacement in content:
            continue
        if content.count(original) != 1:
            raise RuntimeError(f"Unexpected MNN loader source: {relative}")
        path.write_text(content.replace(original, replacement), encoding="utf-8")


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    """Run a build stage and stop immediately if it fails."""
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> int:
    """Build a pinned native wheel and activate it only after an import check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2))
    parser.add_argument("--source", type=Path, help="Reuse an existing pinned MNN source checkout")
    args = parser.parse_args()
    if sys.platform not in {"linux", "win32"}:
        parser.error("This build helper supports Linux and Windows; macOS is not yet supported.")
    windows = sys.platform == "win32"
    if windows and (platform.machine().lower() not in {"amd64", "x86_64"} or sys.maxsize <= 2**32):
        parser.error("Windows builds require x64 Python and an x64 MSVC toolchain.")
    if windows and os.environ.get("VSCMD_ARG_TGT_ARCH", "x64").lower() != "x64":
        parser.error("Run this helper from the x64 Native Tools Command Prompt for Visual Studio.")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    for tool in ("uv", "git", "cmake", "ninja"):
        if shutil.which(tool) is None:
            parser.error(f"Required build tool is missing: {tool}")
    if windows:
        for tool in ("cl", "link", "rc"):
            if shutil.which(tool) is None:
                parser.error(
                    f"Required MSVC/Windows SDK tool is missing: {tool}. Install Visual Studio "
                    "Build Tools with Desktop development with C++ and a Windows SDK, then run "
                    "from the x64 Native Tools Command Prompt for Visual Studio."
                )
    elif shutil.which("c++") is None:
        parser.error("Required build tool is missing: c++")

    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    cache = user_cache_path("placeholder-upscaler", appauthor=False) / f"mnn-{MNN_VERSION}"
    cache.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve() if args.source else cache / "source"
    if not source.exists():
        run(
            [
                "git",
                "clone",
                "--branch",
                MNN_VERSION,
                "--depth",
                "1",
                "https://github.com/alibaba/MNN.git",
                str(source),
            ]
        )
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if commit != MNN_COMMIT:
        raise RuntimeError(f"Unexpected MNN source revision: {commit}; expected {MNN_COMMIT}")
    if not windows:
        patch_linux_loaders(source)

    # A uv-managed Python includes development headers, unlike many OS installs.
    run(["uv", "python", "install", version])
    build_env = cache / f"build-env-{version}"
    python_path = build_env / "Scripts" / "python.exe" if windows else build_env / "bin" / "python"
    if not python_path.is_file():
        run(["uv", "venv", "--python", version, "--managed-python", str(build_env)])
    python = str(python_path)
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "setuptools==84.2.1",
            "wheel==0.48.0",
            "numpy>=2.5.4,<3",
        ]
    )
    build = source / "pymnn_build"
    if windows:
        # Match upstream setup.py's /MT extension and protobuf's static runtime.
        platform_options = [
            "-DCMAKE_C_COMPILER=cl",
            "-DCMAKE_CXX_COMPILER=cl",
            "-DMNN_WIN_RUNTIME_MT=ON",
        ]
    else:
        platform_options = [
            "-DCMAKE_EXE_LINKER_FLAGS=-Wl,-z,noexecstack",
            "-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,noexecstack",
        ]
    run(
        [
            "cmake",
            "-S",
            str(source),
            "-B",
            str(build),
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            # MNN forces __STRICT_ANSI__; use strict C++11 consistently with GCC 16.
            "-DCMAKE_CXX_EXTENSIONS=OFF",
            "-DMNN_OPENCL=ON",
            "-DMNN_VULKAN=ON",
            "-DMNN_VULKAN_IMAGE=OFF",
            "-DMNN_BUILD_SHARED_LIBS=OFF",
            "-DMNN_SEP_BUILD=OFF",
            "-DMNN_BUILD_TRAIN=ON",
            "-DMNN_BUILD_CONVERTER=ON",
            "-DMNN_BUILD_TORCH=OFF",
            "-DMNN_BUILD_OPENCV=ON",
            "-DMNN_IMGCODECS=ON",
            "-DMNN_BUILD_AUDIO=ON",
            "-DMNN_AAPL_FMWK=OFF",
            *platform_options,
        ]
    )
    run(
        [
            "cmake",
            "--build",
            str(build),
            "--target",
            "MNN",
            "MNNTrain",
            "MNNConvertDeps",
            "--parallel",
            str(args.jobs),
        ]
    )
    package = source / "pymnn" / "pip_package"
    build_settings = os.environ.copy()
    if windows:
        # Use the same initialized MSVC environment for CMake and setuptools.
        build_settings["DISTUTILS_USE_SDK"] = "1"
    else:
        build_settings["LDFLAGS"] = "-Wl,-z,noexecstack"
    run(
        [python, "setup.py", "build_ext", "--force", "bdist_wheel", "--deps", "opencl,vulkan"],
        cwd=package,
        env=build_settings,
    )
    wheels = sorted(
        (package / "dist").glob("mnn_vulkan_opencl-*.whl"), key=lambda p: p.stat().st_mtime
    )
    if not wheels:
        raise RuntimeError("The MNN build did not produce a GPU-enabled wheel.")

    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"mnn-{MNN_VERSION}-{uuid4().hex[:12]}"
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            sys.executable,
            "--no-deps",
            "--target",
            str(target),
            str(wheels[-1]),
        ]
    )
    probe_env = os.environ.copy()
    probe_env["PYTHONPATH"] = str(target)
    run(
        [
            sys.executable,
            "-c",
            "import MNN; "
            "print('OpenCL:', MNN.Interpreter.createRuntime(({'backend': 3},))[1][0]); "
            "print('Vulkan:', MNN.Interpreter.createRuntime(({'backend': 7},))[1][0])",
        ],
        env=probe_env,
    )
    manifest = root / f".active-{uuid4().hex}.json"
    manifest.write_text(
        json.dumps(
            {
                "directory": target.name,
                "version": MNN_VERSION,
                "source_commit": MNN_COMMIT,
                "compiled_backends": ["OpenCL", "Vulkan"],
                "linux_runtime_sonames": not windows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest.replace(root / "active.json")
    print(f"GPU-enabled MNN runtime installed in {target}", flush=True)
    print("Restart the app, or click Retry setup / check GPU.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"GPU runtime build failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
