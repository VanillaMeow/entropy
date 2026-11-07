"""Discover the locally built GPU runtime without modifying the uv environment."""

import json
import sys
from importlib import invalidate_caches
from pathlib import Path
from typing import Any

from placeholder_upscaler.paths import runtime_root


def activate_local_runtime() -> dict[str, Any] | None:
    """Prefer a GPU runtime installed by the build helper for this Python ABI."""
    root = runtime_root()
    manifest = root / "active.json"
    if not manifest.is_file():
        return None
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    directory = metadata["directory"]
    if (
        not isinstance(directory, str)
        or directory in {"", ".", ".."}
        or Path(directory).name != directory
    ):
        raise ValueError("Invalid local MNN runtime path in active.json.")
    target = root / directory
    if not (target / "MNN" / "__init__.py").is_file():
        raise ValueError("The local GPU runtime is incomplete. Rerun the MNN build helper.")
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
        invalidate_caches()
    return metadata
