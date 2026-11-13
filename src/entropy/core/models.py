"""Install the pinned default enhancement model automatically and verify its bytes."""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

from entropy.core.config import ModelProfile
from entropy.paths import data_dir, is_compiled

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class ModelArtifact:
    """Immutable provenance and integrity metadata for a downloadable model."""

    name: str
    url: str
    sha256: str
    size: int

    @property
    def filename(self) -> str:
        """Cache filename, versioned by digest so a new model never reuses old bytes."""
        return f'{self.name}-{self.sha256[:12]}.mnn'


DEFAULT_MODEL = ModelArtifact(
    name='realesr-general-x4v3',
    url='https://raw.githubusercontent.com/Lucchetto/Real-ESRGAN-models/'
    '095c5d0cf5ae6bd23e7d6b046cac5f63e8b4ecc8/realesr-general-x4v3.mnn',
    sha256='4a8999e30500cd550cc807b53a6af8153390aa39bdc61b2fe53b20c2141dc442',
    size=4_865_320,
)
DEFAULT_PROFILE = ModelProfile(scale=4)

# Download in small chunks so progress updates stay smooth
DOWNLOAD_CHUNK = 64 * 1024

# Hash cached files in larger chunks, there is no progress to report
HASH_CHUNK = 1024 * 1024


class ModelInstallError(RuntimeError):
    """The default model could not be downloaded or verified."""


def ensure_default_model(
    *,
    directory: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Return a verified model, downloading once into persistent user storage.

    Downloads use a unique scratch file, a pinned HTTPS URL, an exact byte limit,
    and SHA-256 validation before publication. A verified cached model works
    offline. Concurrent instances may download twice but only publish valid bytes.
    """
    artifact = DEFAULT_MODEL

    # Packaged builds ship the model and never download one
    if (bundled := _bundled_directory(directory)) is not None:
        return _bundled_model(bundled, artifact)

    directory = directory if directory is not None else data_dir() / 'models'
    destination = directory / artifact.filename

    # A cached file is re-hashed every time, so a damaged copy is replaced
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if not (destination.is_file() and _valid_file(destination, artifact)):
            _download(artifact, destination, progress)
    except (OSError, URLError) as exc:
        msg = f'Could not install the enhancement model: {exc}. Check your connection and retry.'
        raise ModelInstallError(msg) from exc
    return destination


def _bundled_directory(directory: Path | None) -> Path | None:
    """Where a packaged build ships the model, unless the caller chose a directory."""
    if directory is not None:
        return None

    # The Flatpak sets this, the Windows build keeps models next to the executable
    if configured := os.environ.get('ENTROPY_MODEL_DIR'):
        return Path(configured)
    return Path(sys.executable).parent / 'models' if is_compiled() else None


def _bundled_model(directory: Path, artifact: ModelArtifact) -> Path:
    """Return the shipped model, which must never be replaced by a download."""
    path = directory / artifact.filename

    try:
        valid = path.is_file() and _valid_file(path, artifact)
    except OSError as exc:
        msg = 'Could not read the bundled enhancement model.'
        raise ModelInstallError(msg) from exc

    if not valid:
        msg = 'The bundled enhancement model is damaged. Reinstall Entropy.'
        raise ModelInstallError(msg)
    return path


def _download(
    artifact: ModelArtifact, destination: Path, progress: Callable[[int, int], None] | None
) -> None:
    """Fetch into a scratch file beside the destination and publish it only once verified.

    The scratch file is removed on every exit; after a successful rename it is
    already gone, which NamedTemporaryFile tolerates.
    """
    with NamedTemporaryFile(
        dir=destination.parent, prefix='.model-', suffix='.part', delete_on_close=False
    ) as stream:
        _receive(artifact, stream, progress)
        stream.close()

        # The model's license travels with it
        license_file = files('entropy') / 'licenses' / 'Real-ESRGAN.txt'
        license_text = license_file.read_text(encoding='utf-8')
        destination.with_suffix('.license.txt').write_text(license_text, encoding='utf-8')

        # Renaming within one directory is atomic, so the model appears complete or not at all
        Path(stream.name).replace(destination)


def _receive(
    artifact: ModelArtifact, stream: IO[bytes], progress: Callable[[int, int], None] | None
) -> None:
    """Stream the pinned URL into ``stream``, enforcing HTTPS, the exact size and digest."""
    if not artifact.url.startswith('https://'):
        msg = f'Refusing to download the model over a non-HTTPS URL: {artifact.url}'
        raise ModelInstallError(msg)

    if progress:
        progress(0, artifact.size)

    request = Request(artifact.url, headers={'User-Agent': 'Entropy/0.1'})  # ruff: ignore[suspicious-url-open-usage] - checked above
    digest = hashlib.sha256()
    count = 0

    with urlopen(request, timeout=30) as response:  # ruff: ignore[suspicious-url-open-usage] - checked above
        # A redirect could otherwise quietly downgrade the connection
        if response.geturl().split(':', 1)[0] != 'https':
            msg = 'The model download was redirected to a non-HTTPS URL.'
            raise ModelInstallError(msg)

        # Stop as soon as the size is exceeded instead of filling the disk
        while chunk := response.read(DOWNLOAD_CHUNK):
            count += len(chunk)
            if count > artifact.size:
                msg = 'The model download exceeded its expected size.'
                raise ModelInstallError(msg)

            digest.update(chunk)
            stream.write(chunk)
            if progress:
                progress(count, artifact.size)

    if count != artifact.size or digest.hexdigest() != artifact.sha256:
        msg = 'The model download failed its integrity check. Please retry.'
        raise ModelInstallError(msg)


def _valid_file(path: Path, artifact: ModelArtifact) -> bool:
    """Check a file's size, then its digest, against the artifact."""
    # The size check is free and catches most partial or wrong files
    if path.stat().st_size != artifact.size:
        return False

    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(HASH_CHUNK), b''):
            digest.update(chunk)

    return digest.hexdigest() == artifact.sha256
