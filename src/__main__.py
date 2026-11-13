"""Start the desktop application or, with ``--worker``, its inference process."""

from __future__ import annotations

import sys


def main() -> int:
    """Dispatch to the worker or the GUI, importing only the side this process needs."""
    if sys.argv[1:2] == ['--worker']:
        from src.worker.process import main as worker_main

        del sys.argv[1]
        return worker_main()

    from src.application import run

    return run()


if __name__ == '__main__':
    raise SystemExit(main())
