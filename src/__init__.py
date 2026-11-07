"""Entropy: desktop image upscaling with MNN and Qt."""


def main() -> int:
    """Start the desktop application."""
    from .app import run

    return run()
