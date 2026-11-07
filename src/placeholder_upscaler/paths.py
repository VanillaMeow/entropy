"""Per-user storage shared by the GUI, workers, and native build helper."""

import platform
import sys
from pathlib import Path

from platformdirs import user_data_path


def data_dir() -> Path:
    """Return persistent application data without depending on Qt."""
    return user_data_path("placeholder-upscaler", appauthor=False)


def runtime_root() -> Path:
    """Keep native runtime installations separate for each Python ABI/platform."""
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}-{sys.platform}-{platform.machine()}"
    return data_dir() / "runtimes" / tag
