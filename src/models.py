"""Install the pinned default enhancement model automatically and verify its bytes."""

import hashlib
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import ModelProfile
from .paths import data_dir, is_compiled


@dataclass(frozen=True)
class ModelArtifact:
    """Immutable provenance and integrity metadata for a downloadable model."""

    name: str
    url: str
    sha256: str
    size: int


DEFAULT_MODEL = ModelArtifact(
    name="realesr-general-x4v3",
    url="https://raw.githubusercontent.com/Lucchetto/Real-ESRGAN-models/"
    "095c5d0cf5ae6bd23e7d6b046cac5f63e8b4ecc8/realesr-general-x4v3.mnn",
    sha256="4a8999e30500cd550cc807b53a6af8153390aa39bdc61b2fe53b20c2141dc442",
    size=4_865_320,
)
DEFAULT_PROFILE = ModelProfile(scale=4)


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
    bundled_directory = os.environ.get("ENTROPY_MODEL_DIR") if directory is None else None
    if directory is None and not bundled_directory and is_compiled():
        bundled_directory = str(Path(sys.executable).parent / "models")
    if bundled_directory:
        bundled = Path(bundled_directory) / f"{artifact.name}-{artifact.sha256[:12]}.mnn"
        try:
            if bundled.is_file() and _valid_file(bundled, artifact):
                return bundled
        except OSError as exc:
            raise ModelInstallError("Could not read the bundled enhancement model.") from exc
        raise ModelInstallError("The bundled enhancement model is damaged. Reinstall Entropy.")
    directory = directory if directory is not None else data_dir() / "models"
    destination = directory / f"{artifact.name}-{artifact.sha256[:12]}.mnn"
    scratch: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and _valid_file(destination, artifact):
            return destination
        if progress:
            progress(0, artifact.size)
        request = Request(artifact.url, headers={"User-Agent": "Entropy/0.1"})
        digest = hashlib.sha256()
        count = 0
        with urlopen(request, timeout=30) as response:
            if response.geturl().split(":", 1)[0] != "https":
                raise ModelInstallError("The model download was redirected to a non-HTTPS URL.")
            with NamedTemporaryFile(
                dir=directory, prefix=".model-", suffix=".part", delete=False
            ) as stream:
                scratch = Path(stream.name)
                while chunk := response.read(64 * 1024):
                    count += len(chunk)
                    if count > artifact.size:
                        raise ModelInstallError("The model download exceeded its expected size.")
                    digest.update(chunk)
                    stream.write(chunk)
                    if progress:
                        progress(count, artifact.size)
        if count != artifact.size or digest.hexdigest() != artifact.sha256:
            raise ModelInstallError("The model download failed its integrity check. Please retry.")
        license_text = (
            files(__package__).joinpath("licenses/Real-ESRGAN.txt").read_text(encoding="utf-8")
        )
        destination.with_suffix(".license.txt").write_text(license_text, encoding="utf-8")
        scratch.replace(destination)
        return destination
    except (OSError, URLError) as exc:
        raise ModelInstallError(
            f"Could not install the enhancement model: {exc}. Check your connection and retry."
        ) from exc
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)


def _valid_file(path: Path, artifact: ModelArtifact) -> bool:
    if path.stat().st_size != artifact.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == artifact.sha256
