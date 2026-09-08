"""Where the bundle's vendored dependencies live.

The bundle ships its own CPython, so the ABI is no longer the host's to
choose and the fan-out that used to exist here — one directory per supported
CPython version, picked at import time — has collapsed to one directory named
for the platform. `launch.sh` sets PYTHONPATH to the same place; this module
is what keeps the entry point working when it is run directly.

The old per-ABI directories are still offered afterwards so a bundle unpacked
from an earlier build imports rather than exploding.
"""

from __future__ import annotations

import sys

LEGACY_ABIS = ((3, 12), (3, 13), (3, 14))


def current_platform() -> str:
    machine = "arm64" if sys.platform == "darwin" else "x86_64"
    return f"{sys.platform}-{machine}"


def vendored_lib_dirs(
    bundle_root: str,
    platform: str | None = None,
    version: tuple[int, int] | None = None,
) -> list[str]:
    """Candidate dependency directories, most specific first."""
    platform = platform or current_platform()
    if version is None:
        version = (sys.version_info.major, sys.version_info.minor)

    root = bundle_root.rstrip("/")
    ordered = [version] + [v for v in LEGACY_ABIS if v != version]
    return (
        [f"{root}/lib/{platform}"]
        + [f"{root}/lib/py{major}{minor}" for major, minor in ordered]
        + [f"{root}/lib"]
    )
