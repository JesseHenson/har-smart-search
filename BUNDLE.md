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
`whats_new` has two genuine snapshots to compare.
