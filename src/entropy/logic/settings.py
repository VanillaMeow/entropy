"""Typed access to persisted user preferences."""

from __future__ import annotations

import math

from PySide6.QtCore import QSettings


class Settings:
    """Read preferences as the type of their default, never trusting stored values.

    QSettings returns ``object``, and INI-backed stores hand back strings. A
    missing or malformed value falls back to the default instead of raising.
    """

    def __init__(self, store: QSettings | None = None) -> None:
        # Keep the identity used before the Entropy rename so preferences survive
        self.store = store or QSettings('PlaceholderUpscaler', 'PlaceholderUpscaler')

    def get[T: (bool, int, float, str)](self, key: str, default: T) -> T:
        """Return the stored value converted to the default's type, or the default."""
        value: object = self.store.value(key)
        if value is None:
            return default

        # Every backend can round-trip through text, so convert from that
        text = str(value).strip()

        # Bool is checked before int because bool is a subclass of int
        try:
            if isinstance(default, bool):
                return {'true': True, 'false': False}[text.lower()]

            if isinstance(default, int):
                return int(text)

            if isinstance(default, float):
                number = float(text)
                return number if math.isfinite(number) else default
        except KeyError, ValueError:
            return default

        return text

    def set(self, key: str, value: bool | float | str) -> None:
        """Store a preference."""
        self.store.setValue(key, value)
