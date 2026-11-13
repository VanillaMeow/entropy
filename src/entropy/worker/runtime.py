"""Discover the locally built GPU runtime without modifying the uv environment."""

from __future__ import annotations

import json
import sys
from importlib import invalidate_caches
from pathlib import Path
from typing import Any

from entropy.paths import is_compiled, runtime_root


def activate_local_runtime() -> dict[str, Any] | None:
    """Prefer a GPU runtime installed by the build helper for this Python ABI."""
    # The compiled app bundles its own MNN and must never pick up a dev build
    if is_compiled():
        return None

    root = runtime_root()
    manifest = root / 'active.json'
    if not manifest.is_file():
        return None

    # The manifest names a sibling directory, anything else could escape the root
    metadata = json.loads(manifest.read_text(encoding='utf-8'))
    directory = metadata['directory']
    if (
        not isinstance(directory, str)
        or directory in {'', '.', '..'}
        or Path(directory).name != directory
    ):
        msg = 'Invalid local MNN runtime path in active.json.'
        raise ValueError(msg)

    target = root / directory
    if not (target / 'MNN' / '__init__.py').is_file():
        msg = 'The local GPU runtime is incomplete. Rerun the MNN build helper.'
        raise ValueError(msg)

    # Put the runtime ahead of site-packages so it shadows any CPU-only MNN wheel
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
        invalidate_caches()

    return metadata
