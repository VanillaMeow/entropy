"""Default model downloads are verified, recoverable and reusable offline."""

import hashlib
from io import BytesIO
from pathlib import Path
from urllib.error import URLError

import pytest

from src import models


class Download(BytesIO):
    def geturl(self) -> str:
        return "https://example.com/model.mnn"


@pytest.fixture
def artifact(monkeypatch: pytest.MonkeyPatch) -> bytes:
    payload = b"model weights" * 1024
    monkeypatch.setattr(
        models,
        "DEFAULT_MODEL",
        models.ModelArtifact(
            "test-model",
            "https://example.com/model.mnn",
            hashlib.sha256(payload).hexdigest(),
            len(payload),
        ),
    )
    return payload


def test_verified_install_then_offline_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes
) -> None:
    monkeypatch.setattr(models, "urlopen", lambda *_, **__: Download(artifact))
    progress = []
    path = models.ensure_default_model(
        directory=tmp_path, progress=lambda d, t: progress.append((d, t))
    )
    assert path.read_bytes() == artifact
    assert progress[0] == (0, len(artifact))
    assert progress[-1] == (len(artifact), len(artifact))
    assert "Xintao Wang" in path.with_suffix(".license.txt").read_text()

    def offline(*_: object, **__: object) -> Download:
        raise URLError("offline")

    monkeypatch.setattr(models, "urlopen", offline)
    assert models.ensure_default_model(directory=tmp_path) == path


@pytest.mark.parametrize("payload", [b"truncated", b"x" * (13 * 1024), b"x" * (13 * 1024 + 1)])
def test_bad_download_is_never_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes, payload: bytes
) -> None:
    monkeypatch.setattr(models, "urlopen", lambda *_, **__: Download(payload))
    with pytest.raises(models.ModelInstallError):
        models.ensure_default_model(directory=tmp_path)
    assert not list(tmp_path.glob("*.mnn"))
    assert not list(tmp_path.glob("*.part"))


def test_corrupt_cache_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes
) -> None:
    monkeypatch.setattr(models, "urlopen", lambda *_, **__: Download(artifact))
    path = models.ensure_default_model(directory=tmp_path)
    path.write_bytes(b"x" * len(artifact))
    assert models.ensure_default_model(directory=tmp_path).read_bytes() == artifact


def test_network_failure_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: bytes
) -> None:
    def offline(*_: object, **__: object) -> Download:
        raise URLError("offline")

    monkeypatch.setattr(models, "urlopen", offline)
    with pytest.raises(models.ModelInstallError, match="Check your connection and retry"):
        models.ensure_default_model(directory=tmp_path)
