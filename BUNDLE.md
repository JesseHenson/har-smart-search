# HAR Smart Search — build and install

## Build

    cd "/Users/jessehenson/Development/HAR Real Estate Work"
    uv sync
    for v in 3.12 3.13 3.14; do
      uv pip install --target "lib/py${v/./}" --python "$v" \
        -r <(uv export --no-hashes --no-dev)
    done
    rm -f lib/*/*.pth && rm -rf lib/*/bin
    npx @anthropic-ai/mcpb pack

Dependencies are vendored once per supported CPython ABI, because the
compiled wheels (`pydantic_core`, `_cffi_backend`) only load on the
version they were built for — and the host interpreter is not ours to
choose. Claude Desktop resolves it from PATH. `server/libdir.py` picks
the matching directory at startup, before any third-party import.

Adding a Python version means vendoring for it, listing it in
`libdir.SUPPORTED`, and widening `compatibility.runtimes.python`.

`pack` names the output after the directory it runs in, not after the
manifest — rename the result to `har-smart-search-<version>.mcpb` before
handing it to anyone.

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
