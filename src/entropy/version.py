"""Application version shared by the interface and release packaging."""

from __future__ import annotations

import re
from importlib.metadata import version

# PEP 440 pre-release letters and the words used in release tags
PRERELEASES = {'a': 'alpha', 'b': 'beta', 'rc': 'rc'}


def application_version() -> str:
    """Return the installed package version in release tag format.

    ``0.2.1a2`` becomes ``0.2.1-alpha.2``, matching the GitHub release tags.
    """
    return re.sub(
        r'(a|b|rc)(\d+)$',
        lambda match: f'-{PRERELEASES[match[1]]}.{match[2]}',
        version('entropy'),
    )
