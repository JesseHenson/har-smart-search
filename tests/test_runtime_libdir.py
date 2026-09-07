"""The bundle vendors compiled wheels, which are ABI-specific."""

import sys

from har_search.server.libdir import vendored_lib_dirs


def test_the_interpreters_own_abi_directory_comes_first():
    """Vendored wheels carry native .so files built for one CPython ABI.

    A single flat lib/ therefore only works on the exact version it was
    built against, and the host's Python is not ours to choose — Claude
    Desktop resolves it from PATH. Shipping one directory per supported
    ABI and selecting at import time is what makes the bundle portable.
    """
    dirs = vendored_lib_dirs("/bundle", version=(3, 14))

    assert dirs[0] == "/bundle/lib/py314"


def test_the_flat_directory_remains_a_fallback():
    """Older bundles vendored straight into lib/. Keeping it last means an
    unpacked bundle built the old way still imports rather than exploding.
    """
    dirs = vendored_lib_dirs("/bundle", version=(3, 14))

    assert dirs[-1] == "/bundle/lib"


def test_other_supported_abis_are_offered_after_the_exact_match():
    """Pure-Python packages work on any ABI, so a near-miss still beats
    nothing: if the exact directory is absent, another version's pure
    modules can still satisfy most imports and the failure that follows
    names the missing binary rather than the whole package.
    """
    dirs = vendored_lib_dirs("/bundle", version=(3, 12))

    assert dirs[0] == "/bundle/lib/py312"
    assert "/bundle/lib/py313" in dirs
    assert "/bundle/lib/py314" in dirs


def test_it_works_for_the_running_interpreter_by_default():
    expected = f"/bundle/lib/py{sys.version_info.major}{sys.version_info.minor}"

    assert vendored_lib_dirs("/bundle")[0] == expected
