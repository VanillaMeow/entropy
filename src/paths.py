"""Per-user storage shared by the GUI, workers, and native build helper."""

import platform
import sys
from typing import TYPE_CHECKING

from platformdirs import user_cache_path, user_data_path

if TYPE_CHECKING:
    from pathlib import Path

# Kept from before the rename so existing models and runtimes stay available
APP_DIRECTORY = 'placeholder-upscaler'


def is_compiled() -> bool:
    """Whether this module is running inside the Nuitka application."""
    return '__compiled__' in globals()


def data_dir() -> Path:
    """Return persistent application data without depending on Qt."""
    return user_data_path(APP_DIRECTORY, appauthor=False)


def cache_dir() -> Path:
    """Return disposable cached data, such as native build trees."""
    return user_cache_path(APP_DIRECTORY, appauthor=False)


def runtime_root() -> Path:
    """Keep native runtime installations separate for each Python ABI/platform."""
    tag = f'cp{sys.version_info.major}{sys.version_info.minor}-{sys.platform}-{platform.machine()}'
    return data_dir() / 'runtimes' / tag
