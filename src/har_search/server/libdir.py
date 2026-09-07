"""Where the bundle's vendored dependencies live for this interpreter.

The bundle ships compiled wheels — `pydantic_core`, `_cffi_backend` — whose
`.so` files are built against one CPython ABI. Which interpreter runs us is
not our choice: Claude Desktop resolves it from PATH, and that has already
produced a 3.14 on one machine and refused to start on another because a
pyenv shim shadowed `python`. So the bundle carries one directory per
supported ABI and picks at import time, before anything is imported from
them.
"""

from __future__ import annotations

import sys

# Kept in step with `compatibility.runtimes.python` in manifest.json and with
# what BUNDLE.md vendors. Adding a version here without vendoring for it just
# yields a directory that does not exist, which is skipped harmlessly.
SUPPORTED = ((3, 12), (3, 13), (3, 14))


def vendored_lib_dirs(
    bundle_root: str, version: tuple[int, int] | None = None
) -> list[str]:
    """Candidate dependency directories, most specific first.

    The exact-ABI directory leads. Other supported ABIs follow, because pure
    Python packages import fine from any of them and a near-miss fails on the
    one binary it actually needs rather than on the first import. The flat
    `lib/` trails as a fallback so bundles built before this layout still run.
    """
    if version is None:
        version = (sys.version_info.major, sys.version_info.minor)

    ordered = [version] + [v for v in SUPPORTED if v != version]
    root = bundle_root.rstrip("/")
    return [f"{root}/lib/py{major}{minor}" for major, minor in ordered] + [
        f"{root}/lib"
    ]
