# HAR Smart Search — build and install

## Build

    cd "/Users/jessehenson/Development/HAR Real Estate Work"
    uv sync

    # The interpreter. Apple Silicon only — see below.
    mkdir -p runtime && cd runtime
    curl -sLO https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.13.15+20260901-aarch64-apple-darwin-install_only.tar.gz
    mkdir -p darwin-arm64
    tar xzf cpython-3.13.15+20260901-aarch64-apple-darwin-install_only.tar.gz \
      -C darwin-arm64 --strip-components=1
    rm cpython-*.tar.gz
    find darwin-arm64 -type d \( -name test -o -name tests -o -name idlelib \
      -o -name tkinter -o -name turtledemo \) -exec rm -rf {} +
    rm -rf darwin-arm64/include darwin-arm64/lib/python3.13/config-*
    cd ..

    # Dependencies, once, for the interpreter above.
    rm -rf lib && mkdir -p lib/darwin-arm64
    uv pip install --target lib/darwin-arm64 \
      --python-platform aarch64-apple-darwin --python-version 3.13 \
      -r <(uv export --no-hashes --no-dev)
    rm -f lib/*/*.pth && rm -rf lib/*/bin

    npx @anthropic-ai/mcpb pack

The bundle ships its own CPython. Claude Desktop used to resolve `python3`
from PATH, which is not ours to choose: it produced a 3.14 on one machine, a
pyenv shim on another, and on a clean Mac nothing at all, since the system
`python3` is a stub that only offers to install Xcode. Carrying the
interpreter also collapses the dependency fan-out — one ABI to serve instead
of three — so the bundle got simpler and barely larger.

`bin/launch.sh` is the entry point, run as `sh launch.sh` so it does not
depend on its own execute bit surviving the archive. The interpreter's execute
bit does, which is worth checking after any change to how the bundle is
packed.

**Apple Silicon only, and not by choice.** `cryptography`, pulled in by the
MCP SDK through `pyjwt[crypto]`, stopped publishing x86_64 macOS wheels as of
50.0.1 — the only macOS wheels it ships are `macosx_11_0_arm64`. Supporting
Intel would mean building it from source with a Rust toolchain on the user's
machine, which is not something a bundle can promise. Revisit if that upstream
decision changes, or if the SDK stops pulling the `crypto` extra.

Verify the build before shipping it. Unzip it somewhere else and import
the server with only the bundle on the path:

    PYTHONPATH=<unpacked>/src:<unpacked>/lib python3.12 -c \
      "import har_search; print(har_search.__file__)"

The printed path must be inside the unpacked bundle. If it points back at
this checkout, an editable `.pth` got vendored and the bundle is testing
your working tree rather than itself.

## Install

Open the generated `.mcpb` in Claude Desktop and supply an Apify API token
when prompted.

## Smoke test before a demo

    HAR_APIFY_TOKEN=... uv run python scripts/smoke_run.py

Run this once several days before the demo and again on the day, so
`whats_new` has two genuine snapshots to compare. The script writes to the
same database the MCP server reads (`~/.har-smart-search/har.db`, or
`HAR_DB_PATH` if set) and derives its saved-search key from the criteria the
same way the `search` tool does, so both runs land in the database the demo
will actually query, in the same bucket.

The script prints the `saved_search` key it used — note it down. Pass that
exact key to `whats_new` on demo day to diff the two runs.
