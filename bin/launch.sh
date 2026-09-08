#!/bin/sh
# Start the server on the interpreter shipped inside this bundle.
#
# Claude Desktop used to resolve `python3` from PATH, which is not ours to
# choose: it produced a 3.14 on one machine, a pyenv shim on another, and on a
# clean Mac nothing at all, since the system `python3` is a stub that only
# offers to install Xcode. The bundle now carries CPython, so the host needs
# no Python of its own and the three-ABI dependency fan-out is gone with it.
#
# Apple Silicon only, and not by choice: `cryptography`, pulled in by the MCP
# SDK through pyjwt[crypto], stopped publishing x86_64 macOS wheels. Intel
# would mean building it from source with a Rust toolchain on the user's
# machine, which is not something a bundle can promise.
#
# Invoked as `sh launch.sh`, so this file does not depend on its own execute
# bit surviving the archive. The interpreter's does — see BUNDLE.md.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ARCH=darwin-arm64

PYTHON="$ROOT/runtime/$ARCH/bin/python3"
if [ ! -x "$PYTHON" ]; then
  echo "har-smart-search: no bundled interpreter at $PYTHON" >&2
  echo "har-smart-search: this build requires an Apple Silicon Mac." >&2
  exit 1
fi

PYTHONPATH="$ROOT/lib/$ARCH:$ROOT/src"
export PYTHONPATH
exec "$PYTHON" "$ROOT/src/har_search/server/__main__.py"
