"""Where the bundle's vendored wheels live now that it ships its own Python."""

from har_search.server.libdir import vendored_lib_dirs


def test_the_platform_directory_comes_first():
    """The bundle carries one interpreter, so there is one ABI to serve and
    the directory is named for the platform rather than the Python version.
    `launch.sh` sets PYTHONPATH to the same place; this is what keeps the
    entry point working when it is run directly."""
    dirs = vendored_lib_dirs("/bundle", platform="darwin-arm64")

    assert dirs[0] == "/bundle/lib/darwin-arm64"


def test_the_old_per_abi_directories_remain_a_fallback():
    """A bundle built before the interpreter shipped vendored into lib/pyXYZ.
    Keeping those after the platform directory means an older unpacked bundle
    still imports rather than exploding."""
    dirs = vendored_lib_dirs("/bundle", platform="darwin-arm64", version=(3, 13))

    assert "/bundle/lib/py313" in dirs
    assert dirs.index("/bundle/lib/darwin-arm64") < dirs.index("/bundle/lib/py313")


def test_the_flat_directory_is_last():
    dirs = vendored_lib_dirs("/bundle", platform="darwin-arm64")

    assert dirs[-1] == "/bundle/lib"
