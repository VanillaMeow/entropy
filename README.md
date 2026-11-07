# Entropy

A PySide6 / Qt Quick desktop image upscaler using MNN with OpenCL and Vulkan. The app
installs its default **Real-ESRGAN General 4×** enhancement model automatically.
There is no model file picker or manual model configuration.

## Run

Python 3.11–3.14 and [uv](https://docs.astral.sh/uv/) are supported. Linux is the
currently tested platform.

```bash
uv sync
uv run entropy
```

On first launch, the app downloads and verifies the 4.9 MB default model. It
shows download progress and caches the model for offline use. Add images,
choose the output size and folder, select an available GPU backend, and upscale.
The refresh button beside **GPU processing** retries setup and checks the runtime again.

On this development machine the GPU runtime has already been built and installed.
For a fresh Linux installation, build it once:

```bash
uv run python scripts/build_mnn.py
uv run entropy
```

The build needs `git`, `cmake`, `ninja`, a C++ compiler and internet access. It
uses uv-managed Python development headers and a separate build environment.
Compilation can take several minutes; `--jobs 4` limits parallel compilation.
Neither root privileges nor system-wide library modifications are required.

The runtime is installed in the user's application data directory, separately
from `.venv`. Normal `uv sync` does not remove it. The app prefers this runtime
on subsequent worker launches, including after refreshing GPU setup.
Changing Python minor versions requires rebuilding for that Python ABI.

## Why Vulkan and OpenCL were unavailable

The system drivers work: `vulkaninfo --summary` enumerates the RTX 3080 and Intel
UHD 750, and `clinfo --list` enumerates both GPUs. Two MNN issues caused the failure:

1. The standard MNN 3.6.2 Linux wheel was built without OpenCL and Vulkan.
2. A GPU-enabled build of MNN 3.6.2 searches for `libOpenCL.so` and `libvulkan.so`.
   This system provides the runtime SONAMEs `libOpenCL.so.1` and `libvulkan.so.1`;
   unversioned names usually come from development packages.

The build helper pins MNN to commit
`7e3c6fb5225d3ccf22807ee641332669df34650d` (3.6.2), enables both GPU backends, and
patches their Linux loaders to try the runtime SONAMEs. It also consistently uses
strict C++11 for GCC 16 compatibility and links with a non-executable stack to
avoid the executable-stack loading error found in the original PyPI wheel.

OpenCL and Vulkan runtime loaders and device drivers must still be installed.
MNN selects the device; OpenCL may use the first platform's integrated GPU on
multi-GPU systems. There is no GPU device picker yet. Unsupported individual
operations can still execute on CPU inside an MNN GPU session.

Diagnostics:

```bash
vulkaninfo --summary
clinfo --list
uv run python -m placeholder_upscaler.worker --probe
```

The app's details panel includes the actual imported MNN runtime path, native
logs and setup errors. The optional `uv sync --extra mnn` installs the standard
PyPI wheel for CPU integration testing; it does not enable GPU support.

## Default model

The app uses `realesr-general-x4v3`, a compact general-purpose Real-ESRGAN model
by Xintao Wang, converted to MNN in
[Lucchetto/Real-ESRGAN-models](https://github.com/Lucchetto/Real-ESRGAN-models/tree/mnn).
The download is pinned to conversion commit
`095c5d0cf5ae6bd23e7d6b046cac5f63e8b4ecc8`:

- Size: 4,865,320 bytes.
- SHA-256: `4a8999e30500cd550cc807b53a6af8153390aa39bdc61b2fe53b20c2141dc442`.
- Native enlargement: 4× width and height.
- RGB, float32, 0–1 pixel values, with MNN's packed input tensor layout.

Downloads use a scratch file and are published only after verifying the exact
size and SHA-256. Every reuse checks the cached file's integrity. Corrupt files
are downloaded again; valid files work offline. No images are uploaded. The
[Real-ESRGAN license](src/placeholder_upscaler/licenses/Real-ESRGAN.txt) is included
and copied alongside the downloaded model.

On Linux, persistent files normally live under
`~/.local/share/placeholder-upscaler/`: `models/` for weights and `runtimes/` for
per-Python native packages. Entropy retains this original storage location and
settings identity so existing models, GPU runtimes, and preferences remain available
after the rename. XDG application-data overrides are respected.

## Interface and native file selection

The interface uses Qt Quick Controls with Material styling, shared light/dark
theme tokens, a thumbnail queue, and an asynchronous before/after preview. Narrow
windows move settings into a drawer; advanced tile controls and diagnostics are
loaded on demand. Ctrl+O opens the image chooser. Arrow keys navigate the queue,
and Delete removes the selected queue entry without deleting its files.

On Linux, the app selects Qt's `xdgdesktopportal` platform theme before creating
`QGuiApplication`. QML `FileDialog` and `FolderDialog` use the native
`org.freedesktop.portal.FileChooser` API for image selection, folder import, and
output-folder selection. Qt handles the asynchronous response and the transient
window parent, including Wayland. This selects the portal for this process only.

The PySide6 wheel includes the Qt portal plugin; the desktop needs a running
`xdg-desktop-portal` service and an appropriate backend, such as
`xdg-desktop-portal-kde` or `xdg-desktop-portal-gnome`. When native dialogs are
unavailable Qt can use its QML fallback; a missing plugin is logged.

`app.py` bootstraps the application; `controller.py` exposes typed properties and
actions; `queue.py` supplies the list model. `qml/Main.qml` wires together focused
components for the workspace, comparison, queue, settings, dialogs, and status.
The `qml/components/` directory contains reusable controls and `Theme.qml` holds
the color and typography tokens. Native inference remains in its own process.

## Features and limits

- Batch file/folder import, drag and drop, and original/result comparison.
- Output size presets from 0.25× to 4×, plus custom 10–400% sizing in 1% steps.
  The default remains 4×. Scales above 1× use the 4× enhancement model followed
  by Lanczos resizing to the chosen dimensions. At 1× or below, images are
  resized directly without enhancement, model installation, or a GPU.
  Dimensions round to the nearest pixel, with a minimum of one pixel per side.
- Padded tile inference, configurable tile size/padding, progress and cancellation.
- A separate native inference process, preserving Qt responsiveness.
- Static PNG, JPEG, WebP, TIFF and BMP input; 8-bit RGB/RGBA PNG output.
- EXIF orientation and alpha preservation. Alpha uses Lanczos interpolation.
- Filenames reflect the chosen scale, such as `photo_1.5x.png` or `photo_0.5x.png`.
  Existing files are preserved: `photo_4x.png`, `photo_4x_1.png`, etc.

Folder import is non-recursive. Animated/multipage images are rejected. Output
publication uses exclusive hard links and therefore needs a filesystem supporting
them, such as ext4, Btrfs or NTFS. Completed outputs survive cancellation; the
current output scratch file is removed. Force-killing the entire application can
leave hidden scratch files. An interrupted model download is never treated as an
installed model, but can leave an unused `.model-*.part` file.

Tiling bounds GPU intermediate memory; the complete images still occupy host
RAM. Smaller tiles help with GPU memory pressure. Padding reduces seams but is
not a guarantee of full-frame equivalence. Previews are limited to 2048 pixels
per side. RGB color profiles are retained without explicit color conversion;
non-RGB input profiles are dropped after Pillow's RGB conversion. HDR, video,
scales above 4×, installers and Windows GPU validation are not included.

## Development

```bash
uv sync --extra mnn
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run python scripts/check_qml.py --check
uv run pytest -ra
uv build
```

Normal tests use generated models on CPU to check native tensor conversion,
including packed layouts, plus download integrity/offline reuse, tiling, image
handling, file collisions, batch errors, Qt startup and process cancellation.
They do not require network access. Native CPU tests explicitly skip if MNN
cannot load.

After changing Python properties exposed to QML, regenerate the checked-in
tooling metadata and lint the components with `uv run python scripts/check_qml.py`.
Add `--format` to apply `qmlformat`. CI checks both Python and QML; headless UI tests
load light/dark themes, the compact layout and drawers.

To verify actual portal D-Bus requests in a Linux desktop session:

```bash
UPSCALER_TEST_PORTAL=1 uv run pytest tests/test_portal.py -v
```

This test opens and automatically dismisses all three native pickers. It checks
that each action sends exactly one portal request and needs `dbus-monitor`.

Run the real default model on both GPU backends with:

```bash
UPSCALER_TEST_GPU=1 uv run pytest tests/test_gpu.py -v
```

These tests require the GPU runtime and drivers, and install the pinned model if
it is not cached. They check dynamic tile inference, output dimensions and pixel
sanity. CI covers Python 3.11 and 3.14; GPU tests are opt-in because hosted runners
lack the required GPU hardware. Weekly dependency updates are configured.

Local validation on Aurora 44 with an RTX 3080 and Intel UHD 750: both real-model
GPU tests passed, as did the full Qt Quick setup → automatic model → Vulkan inference
→ RGBA PNG export workflow. Availability is reported by MNN; inference checks
also validate output pixels so a successful probe alone is not treated as proof.
