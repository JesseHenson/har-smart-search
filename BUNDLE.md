# HAR Smart Search — build and install

## Build

    cd "/Users/jessehenson/Development/HAR Real Estate Work"
    uv sync
    uv pip install --target lib -r <(uv export --no-hashes --no-dev)
    npx @anthropic-ai/mcpb pack

Dependencies are vendored into `lib/` so the bundle installs without a
Python environment on the host.

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
