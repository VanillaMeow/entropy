"""Application version shared by the interface and release packaging."""

import re
from importlib.metadata import version


def application_version() -> str:
    """Return the installed package version in release tag format."""
    prereleases = {"a": "alpha", "b": "beta", "rc": "rc"}
    return re.sub(
        r"(a|b|rc)(\d+)$",
        lambda match: f"-{prereleases[match[1]]}.{match[2]}",
        version("entropy"),
    )
