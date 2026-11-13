"""Default model downloads are verified, recoverable and reusable offline."""

import hashlib
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn
from urllib.error import URLError

import pytest

from entropy.core import models


class Download(BytesIO):
    """An in-memory response that reports the HTTPS URL it came from."""

    def geturl(self) -> str:
        return 'https://example.com/model.mnn'


def serve(payload: bytes) -> Callable[..., Download]:
    """A stand-in for urlopen that returns the payload."""

    def urlopen(*_: object, **__: object) -> Download:
        return Download(payload)

    return urlopen


def forbidden(reason: str) -> Callable[..., NoReturn]:
    """A stand-in that fails the test if it is ever called."""

    def fail(*_: object, **__: object) -> NoReturn:
        pytest.fail(reason)

    return fail


def offline(*_: object, **__: object) -> Download:
    """A stand-in for urlopen without a network connection."""
    raise URLError('offline')


@pytest.fixture
def artifact(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """Swap the real model for a small payload, returning its bytes."""
    payload = b'model weights' * 1024
    monkeypatch.setattr(
        models,
        'DEFAULT_MODEL',
        models.ModelArtifact(
            'test-model',
            'https://example.com/model.mnn',
            hashlib.sha256(payload).hexdigest(),
            len(payload),
        ),
    )
    return payload


def test_verified_install_then_offline_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes
) -> None:
    monkeypatch.setattr(models, 'urlopen', serve(artifact))
    progress: list[tuple[int, int]] = []

    path = models.ensure_default_model(
        directory=tmp_path, progress=lambda d, t: progress.append((d, t))
    )

    assert path.read_bytes() == artifact
    assert progress[0] == (0, len(artifact))
    assert progress[-1] == (len(artifact), len(artifact))
    assert 'Xintao Wang' in path.with_suffix('.license.txt').read_text()

    # Once installed, the model keeps working without a connection
    monkeypatch.setattr(models, 'urlopen', offline)
    assert models.ensure_default_model(directory=tmp_path) == path


@pytest.mark.parametrize('payload', [b'truncated', b'x' * (13 * 1024), b'x' * (13 * 1024 + 1)])
def test_bad_download_is_never_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes, payload: bytes
) -> None:
    monkeypatch.setattr(models, 'urlopen', serve(payload))

    with pytest.raises(models.ModelInstallError):
        models.ensure_default_model(directory=tmp_path)

    # Neither a model nor a leftover scratch file may remain
    assert not list(tmp_path.glob('*.mnn'))
    assert not list(tmp_path.glob('*.part'))


def test_corrupt_cache_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes
) -> None:
    monkeypatch.setattr(models, 'urlopen', serve(artifact))
    path = models.ensure_default_model(directory=tmp_path)

    # Same size, wrong bytes, so only the digest check can catch it
    path.write_bytes(b'x' * len(artifact))
    assert models.ensure_default_model(directory=tmp_path).read_bytes() == artifact


def test_network_failure_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes
) -> None:
    monkeypatch.setattr(models, 'urlopen', offline)

    with pytest.raises(models.ModelInstallError, match='Check your connection and retry'):
        models.ensure_default_model(directory=tmp_path)


def test_bundled_model_works_without_network_or_writable_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes
) -> None:
    bundled = tmp_path / models.DEFAULT_MODEL.filename
    bundled.write_bytes(artifact)
    monkeypatch.setenv('ENTROPY_MODEL_DIR', str(tmp_path))

    reason = 'A bundled model must not access the network or user storage'
    monkeypatch.setattr(models, 'urlopen', forbidden(reason))
    monkeypatch.setattr(models, 'data_dir', forbidden(reason))

    assert models.ensure_default_model() == bundled


def test_compiled_app_discovers_the_installed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes
) -> None:
    directory = tmp_path / 'models'
    directory.mkdir()
    bundled = directory / models.DEFAULT_MODEL.filename
    bundled.write_bytes(artifact)

    # The Windows build finds models next to its executable, without the variable
    monkeypatch.delenv('ENTROPY_MODEL_DIR', raising=False)
    monkeypatch.setattr(models, 'is_compiled', lambda: True)
    monkeypatch.setattr(models, 'sys', SimpleNamespace(executable=str(tmp_path / 'Entropy.exe')))
    monkeypatch.setattr(models, 'urlopen', forbidden('The installed model must work offline'))
    monkeypatch.setattr(models, 'data_dir', forbidden('The installation may be read-only'))

    assert models.ensure_default_model() == bundled


@pytest.mark.parametrize('payload', [None, b'corrupt'])
def test_missing_or_damaged_bundle_does_not_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes, payload: bytes | None
) -> None:
    if payload is not None:
        (tmp_path / models.DEFAULT_MODEL.filename).write_bytes(payload)

    monkeypatch.setenv('ENTROPY_MODEL_DIR', str(tmp_path))
    monkeypatch.setattr(
        models, 'urlopen', forbidden('A damaged bundled model must not trigger a download')
    )

    with pytest.raises(models.ModelInstallError, match='Reinstall Entropy'):
        models.ensure_default_model()


def test_explicit_model_directory_takes_precedence_over_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes
) -> None:
    monkeypatch.setenv('ENTROPY_MODEL_DIR', str(tmp_path / 'missing-bundle'))
    monkeypatch.setattr(models, 'urlopen', serve(artifact))

    path = models.ensure_default_model(directory=tmp_path / 'cache')

    assert path.read_bytes() == artifact
