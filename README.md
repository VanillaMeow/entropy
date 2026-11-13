# Entropy

A PySide6 / Qt Quick desktop image upscaler using MNN with OpenCL and Metal backends. The app
installs its default **Real-ESRGAN General 4×** enhancement model automatically.
There is no model file picker or manual model configuration.

The current prerelease is **v0.2.1-alpha.2** (`0.2.1a2` in Python package metadata).

The runtime automatically selects Metal on macOS and OpenCL on Linux and Windows;
backend selection is internal. Metal is groundwork for future macOS support:
macOS runtime builds, packaging, and hardware validation are not yet provided.

## Run

Python 3.14 is required and selected by `.python-version`. Python 3.15 support
is deferred until MNN publishes a compatible wheel. Use
[uv](https://docs.astral.sh/uv/) to manage the environment. Linux is the currently
tested platform. The runtime build helper also supports Windows x64 with MSVC;
native Windows GPU validation is still pending.

For Windows, download and run `entropy-windows-x86_64-setup.exe`. The installer
installs Entropy for the current user under `%LOCALAPPDATA%\Programs\Entropy`,
creates Start menu and desktop shortcuts, and registers an uninstaller in Windows
Settings. Launch **Entropy** from the Start menu. The app includes its dependencies,
the OpenCL runtime and the enhancement model; Python is not required.
Only a compatible GPU driver is needed. The installer displays the full
**Mozilla Public License 2.0** and installs its text alongside the application.

```bash
uv sync
uv run entropy
```

On first launch, the app downloads and verifies the 4.9 MB default model. It
shows download progress and caches the model for offline use. Add images,
choose the output size and folder, and upscale. OpenCL acceleration is automatic.
Use **Retry setup** in **Diagnostics** to retry model installation and check the runtime again.

On this development machine the GPU runtime has already been built and installed.
For a fresh Linux or Windows installation, build it once:

```bash
uv run python scripts/build_mnn.py
uv run entropy
```

The build needs `git`, `cmake`, `ninja`, a C++ compiler and internet access. It
uses uv-managed Python development headers and a separate build environment.
Compilation can take several minutes; `--jobs 4` limits parallel compilation.
Neither root privileges nor system-wide library modifications are required.

On Windows, install Visual Studio 2022 Build Tools with **Desktop development
with C++** and a Windows SDK, plus uv, Git, CMake and Ninja. Open the **x64 Native
Tools Command Prompt for VS 2022**, change to the repository directory, then run:

```bat
uv sync
uv run python scripts/build_mnn.py --jobs 4
uv run entropy
```

Use x64 Python 3.14 and the x64 toolchain. The helper builds OpenCL support
into a static MNN runtime and installs the Python extension for the app; the
standard MNN wheel is not a substitute for this GPU build. Install current GPU
drivers providing OpenCL. A separate OpenCL SDK is not
required. Qt uses its native Windows file dialogs, and output folders must be
on a filesystem with hard-link support, such as NTFS; FAT32/exFAT are unsupported.
macOS runtime builds are not enabled yet.

The runtime is installed in the user's application data directory, separately
from `.venv`. Normal `uv sync` does not remove it. The app prefers this runtime
on subsequent worker launches, including after retrying setup from Diagnostics.
Rebuilding checks that the new runtime imports before switching to it, then
removes runtimes from earlier builds.
Changing Python minor versions requires rebuilding for that Python ABI.

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
[Real-ESRGAN license](src/entropy/licenses/Real-ESRGAN.txt) is included
and copied alongside the downloaded model.

On Linux, persistent files normally live under
`~/.local/share/placeholder-upscaler/`: `models/` for weights and `runtimes/` for
per-Python native packages. Entropy retains this original storage location and
settings identity so existing models, GPU runtimes, and preferences remain available
after the rename. XDG application-data overrides are respected.
On Windows the same data lives under `%LOCALAPPDATA%\placeholder-upscaler\`.

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

The `entropy` package, in `src/entropy`, is split by responsibility:

- `core/` holds pure logic shared by both processes, with no Qt: the request
  model, image tiling, model download, and the typed worker events.
- `worker/` is the inference process: MNN loading and the batch runner.
- `logic/` is the desktop process's state, using QtCore only: the `Session`
  (queue, preferences, batch and setup lifecycle), the image list model, typed
  settings, and the `WorkerHost` that runs and talks to the worker.
- `ui/` is everything Qt Quick touches: the `AppController` view model, the
  preview image provider, and the QML sources.

`application.py` holds `Entropy`, which owns the settings, worker host, session
and interface, and passes itself to each part. The session never calls into the
interface; it emits signals that the view model forwards to QML.

Native inference runs in a separate child process, so a crashing GPU driver
cannot take the app down and a batch can be cancelled even inside a native call.
The desktop app sends the batch request as JSON on the worker's stdin, and the
worker reports one JSON event per line on stdout. MNN prints its own logs to
the same stream, so event lines carry a prefix and all other output goes to the
diagnostics panel. Both sides share the pydantic models in `core/events.py`.

In `ui/qml/`, `Main.qml` wires together focused components for the workspace,
comparison, queue, settings, dialogs, and status. The `components/` directory
contains reusable controls and `Theme.qml` holds the color and typography tokens.

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

## Flatpak

The YAML manifest is `flatpak/io.github.jedace07.Entropy.yaml`. It uses the
Freedesktop 26.08 runtime with Python 3.14, bundles PySide6 wheels, builds the
pinned MNN runtime with OpenCL, and bundles the verified enhancement
model. Python dependencies are downloaded from the pinned sources in
`flatpak/python-dependencies.yaml`.
The build bootstraps a pinned uv executable from `flatpak/uv.yaml` and uses
`uv pip install` to install into `/app`; compilation and installation run offline.

Use the Flatpak-packaged builder. From the repository root, install it from
Flathub, then build and install. The builder installs the required runtime
and SDK system-wide:

```bash
flatpak remote-add --system --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --system flathub org.flatpak.Builder
flatpak run org.flatpak.Builder --system --install-deps-from=flathub --force-clean --jobs=4 --repo=flatpak-repo --install flatpak-build flatpak/io.github.jedace07.Entropy.yaml
flatpak run io.github.jedace07.Entropy
```

All build dependencies and the resulting app use the system installation.
Omit `--install` to build and export locally without installing the app.
The manifest includes Python 3.14 wheels for x86_64 and aarch64. To export a
single-file bundle after building:

```bash
flatpak build-bundle flatpak-repo entropy.flatpak io.github.jedace07.Entropy
```

Filesystem access is read/write for the home directory, `/mnt`, `/media`, and
`/run/media`. Other permissions are limited to GPU rendering and compute,
Wayland, fallback X11, and shared IPC for X11. File pickers and opening output
folders use portals. The sandbox has no network, audio, unrestricted device,
or unrestricted D-Bus permissions. The bundled model makes offline startup
and processing possible without a host Python environment or a user-built MNN
runtime. Host GPU drivers must still be available through Flatpak's graphics
extensions; OpenCL availability depends on the driver's support in the sandbox.

## Automated builds and releases

Push a version tag such as `v0.1.0` to build both x86_64 packages:

- `entropy-x86_64.flatpak` for Linux.
- `entropy-windows-x86_64-setup.exe` for Windows, an offline Qt Installer Framework
  installer containing the standalone application, dependencies, the OpenCL
  runtime, the enhancement model and license texts.

Both builds must succeed before the workflow publishes a GitHub Release with
the two downloads and generated release notes. Run **Publish builds** manually
from the Actions tab to download build artifacts without creating a release.
Ordinary pushes and pull requests do not run a workflow.
Tags with a prerelease suffix, such as `v0.1.0-alpha.1`, publish as GitHub
prereleases; tags such as `v0.1.0` publish as stable releases.

The workflow builds, validates the Windows installation, packages and publishes.
It does not install the `dev` dependency group or run the test suite, GPU inference
tests or lint checks. The Windows
job builds MNN with MSVC, compiles the application with `pyside6-deploy` (Nuitka in
standalone mode), checks that the compiled application can load its workspace
without downloading a model, then wraps it with Qt Installer Framework's `binarycreator`.
Before publishing, it installs the package on Windows, checks the GUI's MNN worker
handshake and the registered uninstall confirmation, verifies cancellation preserves
the application, and confirms removal deletes the app and Windows Settings entry.
The application starts without a console window and uses its own executable for
isolated GPU workers. It reads the bundled model from its installation directory
and keeps user preferences and cached data in the existing per-user locations.
The installer includes Start menu, desktop and uninstall shortcuts, with a
maintenance tool also available through Windows Settings. The application and
its Qt runtime live in the `app/` subdirectory, separate from the maintenance
tool. Setup skips component and Start menu folder selection; uninstall opens
the removal wizard and requires confirmation.

To build the installer locally on Windows, use the x64 Native Tools Command Prompt
and install the build tools and Qt Installer Framework:

```bat
uv sync --group windows-build
uv run --group windows-build aqt install-tool windows desktop tools_ifw qt.tools.ifw.47 --outputdir C:\Qt
uv run --group windows-build python scripts/build_mnn.py --jobs 4
uv run --group windows-build python scripts/package_windows.py --binarycreator C:\Qt\Tools\QtInstallerFramework\4.7\bin\binarycreator.exe
```

You can instead put `binarycreator.exe` on `PATH` or set `QTIFW_BINARYCREATOR` to
its full path. The resulting installer is `dist/entropy-windows-x86_64-setup.exe`.
Packaging derives the installer and executable versions from the same Python
package metadata used by the app's version label. The app's MPL 2.0 license is
shown on the license page and installed as `LICENSE`; the model and dependencies
retain their separate license and notice files. Uninstalling removes installed
application files and shortcuts while preserving per-user preferences and data.

Install a downloaded Flatpak with:

```bash
flatpak install --user entropy-x86_64.flatpak
```

## Development

```bash
uv sync --extra mnn
uv run ruff check
uv run ruff format --check
uv run pyright
uv run python scripts/check_qml.py --check
uv run pytest -ra
uv build
```

Pyright runs in strict mode over `src`, `scripts` and `tests`. PySide6's bundled
type stubs miss a few things, such as typed `Property` descriptors, so
`typings/PySide6` holds patched copies that pyright reads first. Each patch is
marked with a `# Patched:` comment. A stub there replaces the whole module, and
the stubs import each other, so the folder holds every module the project imports
plus everything those modules import in turn. After a PySide6 upgrade, copy the
new stubs over these and reapply the marked patches. Read/write Qt properties use
the explicit form,
`outputScale = Property(float, _get, _set, notify=...)`, since strict pyright
treats the `@x.setter` pattern as a redeclaration.

Normal tests use generated models on CPU to check native tensor conversion,
including packed layouts, plus download integrity/offline reuse, tiling, image
handling, file collisions, batch errors, Qt startup and process cancellation.
They do not require network access. Native CPU tests explicitly skip if MNN
cannot load.

After changing Python properties exposed to QML, regenerate the checked-in
tooling metadata and lint the components with `uv run python scripts/check_qml.py`.
Add `--format` to apply `qmlformat`. These optional checks run locally;
headless UI tests load light/dark themes, the compact layout and drawers.

To verify actual portal D-Bus requests in a Linux desktop session:

```bash
UPSCALER_TEST_PORTAL=1 uv run pytest tests/test_portal.py -v
```

This test opens and automatically dismisses all three native pickers. It checks
that each action sends exactly one portal request and needs `dbus-monitor`.

Run the real default model with OpenCL acceleration:

```bash
UPSCALER_TEST_GPU=1 uv run pytest tests/test_gpu.py -v
```

These tests require the GPU runtime and drivers, and install the pinned model if
it is not cached. They check dynamic tile inference, output dimensions and pixel
sanity. GPU tests are opt-in and require suitable GPU hardware. Weekly dependency
updates are configured.

Availability is reported by MNN; inference checks
also validate output pixels so a successful probe alone is not treated as proof.

## License

Entropy's source code is licensed under the [Mozilla Public License 2.0](LICENSE).
This Source Code Form is subject to the terms of the Mozilla Public License,
v. 2.0. If a copy of the MPL was not distributed with this file, you can obtain
one at https://mozilla.org/MPL/2.0/.

Source code is available at https://github.com/jedace07/entropy; each release's
tag identifies its corresponding source. Bundled third-party dependencies and
the enhancement model retain their own licenses. The model's
[Real-ESRGAN license](src/entropy/licenses/Real-ESRGAN.txt) is included separately.
