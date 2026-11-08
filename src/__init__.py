"""Entropy: desktop image upscaling with MNN and Qt."""

import sys


def main() -> int:
    """Start the desktop application or its isolated inference worker."""
    if sys.argv[1:2] == ["--worker"]:
        from .worker import main as worker_main

        del sys.argv[1]
        return worker_main()

    from .app import run

    return run()
