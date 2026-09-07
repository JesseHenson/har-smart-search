# HAR Smart Search — spec

## Purpose
- **Repeatable parameter search** over HAR listings — same criteria re-run weekly to surface new investment candidates
- **Similarity ranking, not strict filtering** — near-misses (4br when 3br asked, slightly over budget) still surface when the rest fits
- **Per-result value KPI** — each hit compared against nearby comps, so results can be validated and prioritized by price vs neighborhood

## Users
- **MCPB bundle** — each user installs and runs it inside their own Claude
- ? **single-user local install** implies no shared server and no hosted state

## Data
- **Live scrape at query time** — no local snapshot, results are a point-in-time view
- ? **comps radius search** means a second round of fetches per result

### Comps
- **Local cache between runs** so repeat queries and comps lookups avoid re-fetching
- **Cache is local** — see Storage; never chat history
- **No Apify for the POC** — "HAR alone" means one source, and the listing scraper already covers comps
- **Apify kept as fallback** — only if HAR scraping proves brittle, or sold comps get added
- **Swappable comps source** — user may bring their own provider after POC

## Ranking
- **One code path, not two** — HAR fetch is deliberately loose (location plus widened bounds), all scoring happens locally on what comes back
- **Blended soft score** orders every candidate; **location is the only hard gate** for the POC
- **Per-result match badge** — each hit shows which params matched and which were stretched, so a soft hit is never mistaken for an exact one
- ? **strict mode toggle** — offer hard-filter-only ranking later if the user asks for it
- ? **weighting** — how much each param contributes to the blended score

## Output
- **One saved dashboard**, refreshed in place each run — not a new artifact per search
- **Ranked rows** carrying the comps KPI and the match badge together
- **Claude Artifact** as that dashboard — published once, updated in place on later runs
- **Artifact URL persists locally** so later runs update the same dashboard

## Input
- **Criteria live in the dashboard** — user edits fields in the artifact rather than restating params in chat
- **Artifact `db` capability** persists them; Claude reads them back with `read_db` and passes them into the bundle
- ? **dashboard-triggered runs** — artifact `mcp` capability can reach a local MCP server, so a Refresh button could re-run without chat

- **Named searches** — several saved side by side, each re-runnable on its own

## Storage
- **Two stores, split by role** — nothing duplicated between them
- **Artifact `db`**: saved searches, last run's ranked results, artifact URL — the dashboard reads and writes these directly
- **Local SQLite in the bundle**: raw HAR listings and comps responses, the cache that keeps repeat runs cheap
- **Split TTL, not one flat number** — freshness matters per record type
- **Listing search: never cached** — new inventory is exactly what a weekly run hunts
- **Listing detail and comps: 7 days** — details rarely change mid-listing, neighborhood value moves slowly

> **Why split the TTL**
> The two record types move at different speeds. New inventory is the entire reason for a
> weekly run, so a cached listing search would hide the thing being hunted. Neighborhood
> pricing drifts over months, not days — caching comps for a week costs nothing in accuracy
> and saves most of the fetches. One flat TTL would have to pick a loser either way.

## KPI
- **Comps from active listings** for the POC — transcript says "using the HAR website alone" and never mentions sold prices
- **Asking-price caveat** — listed comps skew high; the KPI is a relative signal, not an appraisal
- ? **sold-price comps** — confirm with user; would need a data source beyond public HAR
- **Dollar delta is the headline** — user's own framing: nearby similar homes go for "20,000 more, or 20,000 less"
- **$/sqft shown alongside** — he specifies search input in $/sqft, so the unit is already his
- **Buy-side only** — transcript has no selling; the KPI exists to validate a search and prioritize finds
- **Radius plus similarity gate** — a comp must be both nearby and comparable (beds/sqft band), so outliers do not skew the number
- **Both units first-class** — dollar delta and $/sqft delta shown together, neither buried
- ? **radius size and gate width** — tuning, pick defaults during build

## Tools
- **One MCP tool for the POC** — a single `run_search` call that fetches, scores, comps, and publishes
- **Logic lives in the bundle, not the agent** — Claude passes criteria in and gets a finished run back
- **More tools added only on demand** — split the surface when the agent genuinely needs finer control

> **Why one call to start**
> A multi-tool surface is more flexible, but every extra call is another chance for the agent
> to compose the run differently than last week. One call makes a run reproducible: same
> criteria in, same pipeline every time. Flexibility can be added later by splitting the tool;
> reliability lost to stochastic composition is much harder to win back.

## Params
- **Scoring params, day one**: location (hard gate), price and $/sqft, beds, baths, sqft
- **Display-only**: garage, house age, HOA, property type — shown on the row, never move rank
- ~~Deferred: school rating~~ — **wrong, it is on the record**: the actor returns letter grades and a numeric index per school level
- **Also confirmed present**: `daysOnMarket`, `maintenanceFee` as a structured HOA field, `garage`, lat/lon, and an AVM valuation per property
- ? **which of these get promoted to scoring** — they are available now, the question is only whether they should move rank
- **Tiered weights** over normalized distances — price heaviest, beds/sqft middle, rest light
- ? **user-set weights** — sliders in the dashboard if fixed tiers rank badly

> **Why display-only exists**
> A field that is sometimes blank or buried in listing remarks will parse wrong some of the
> time. If it moves rank, a bad parse silently demotes a good house and the KPI cannot be
> trusted. Showing it costs nothing and loses no information — it just stays out of the math
> until it has proven reliable. Promotion is a one-line change later.

## Access — UNBLOCKED (verified)
- **Direct HTML scraping is dead** — PerimeterX bot wall returns 403 in ~0.2s on every public HAR URL; not worked around
- **Apify actor `memo23/har-scraper` works** — verified live: 5 Spring listings in 31.5s, every field populated
- **Cost measured, not guessed** — $0.005 per run start plus $0.004 per property; a 200-listing weekly run is under $1
- **Sold data reachable** — `listingType: "sold"` returns closed-deal history with final price and date
- **MLS feed still the better endgame** — Mohammad's answer upgrades the adapter; nothing above it changes

> **Why this is a hard blocker, not a detail**
> Every other decision in this spec assumes listing records arrive somehow. The shape of
> those records — fields, freshness, cost per call — is set by whichever access path wins,
> and that reshapes the cache TTLs and the comps strategy. Building the pipeline against a
> guessed record shape means rewriting it once the real one lands.
- **Link out to the listing** on every row — not in the transcript, but the obvious exit to see the house
- **New since last run** flag — transcript's "everything that's come up" is the weekly-run payoff
- **Days on market** display-only, and only if the data source provides it
- **No photos** — nothing in the transcript asks for them, and they slow a scan table down

## Run flow
- **Chat is the progress surface** — dashboard stays showing last week's results until the new run lands, never a spinner
- **Claude narrates the run** from what the tool returns: counts, what's new, what stands out
- **Tool emits MCP progress notifications** during the fetch so long runs are not silent
- ? **progress display** — confirm Claude Desktop surfaces MCP progress notifications; if not, chat narration is post-hoc only
- **Narration is the agent's call** — no fixed template; Claude picks what a real estate investor would care about that week
- **Tool returns the raw material for it** — new count, best and worst deltas, area median $/sqft and its change, biggest movers — so the agent has facts to choose from

## Failure
- **Never blank the dashboard** — last good results stay on screen, they are still the best information available
- **Banner states what happened** — run failed, or returned nothing, with the timestamp of the data actually shown
- **Stale is a visible state, not a silent one** — a week-old table must never read as fresh
- **Partial data still publishes** — listings without comps are worth seeing; the run is only failed when nothing came back
- **Missing pieces marked per row** — a blank delta reads as "not computed", never as "priced at market"

## Build order
- **Storage split stays** — artifact `db` for criteria and published results, local SQLite for the scrape cache
- ? **single-store via local MCP** — parked, revisit only if the split causes real friction
- **Source adapter from day one** — everything downstream takes listing records from an interface, never from a scraper directly
- **Mock source first** — fixture listings let the full pipeline run, be tested, and be demoed while access is blocked
- **Real source drops in later** — when Mohammad answers, only the adapter is written; scorer, comps, storage, and dashboard are untouched

> **Why the adapter is not over-engineering here**
> The access path is genuinely unknown — HAR API, MLS feed, or a paid aggregator each hand
> back a different record shape. An adapter is the cheapest way to keep that uncertainty in
> one file instead of smeared through the scorer and comps math. It also makes the mock a
> first-class citizen, so tests never need a network.

## Onboarding
- **Ships as an MCP prompt, not a skill** — the MCPB manifest schema allows `tools` and `prompts` only; Desktop lists prompts as commands
- **Two prompts**: `getting_started` walks the first run end to end, `plan_search` assembles a full criteria set before running anything
- **Creating the weekly schedule is its job** — the bundle cannot schedule anything itself
- **Done means the user has seen real results** — dashboard published, one saved search in it, weekly schedule live
- **The walkthrough is most of it** — pull the dashboard up and explain the columns, especially what the delta and the match badge mean
- **Ends with a few next moves** — adjust criteria in place, add a second saved search, re-run early if something looks off
- **Criteria gathered in chat first** — no empty dashboard; the artifact appears already full of their results
- **Chat carries the wait** — the first run happens while they are still in conversation, not staring at a blank page

> **Why criteria come before the dashboard**
> An empty dashboard is a form, and a form asks the user to guess what good input looks like.
> Gathering criteria in chat lets Claude ask about area and budget in plain language, fill the
> gaps, and hand over a dashboard whose first impression is a ranked list of real houses —
> the product working, not a setup screen.

- **AVM as a second opinion** — the actor returns a per-property automated valuation; it is an independent check on our comps math, not a replacement

> **Why the deferral list shrank**
> Those fields were deferred on the assumption that HAR's public record would not carry them
> reliably. A live run disproved that: five of five listings came back with garage, HOA fee,
> days on market, school ratings and coordinates all populated. The display-only rule still
> holds as a discipline, but the reason for it is now "unproven under load", not "missing".

## Comp coverage — measured on 103 real sold rows
- **Sold rows are not geographically targeted** — they come from agents' closed-deal history, so a Spring query returns Tomball, Katy and Pearland sales too
- **Distance is not the binding constraint, size is** — three sold comps landed within 1.4 miles of a test subject and all three failed the sqft band (x0.51, x0.72, x0.72)
- **Coverage scales with how many agents are crawled** — `maxSoldAgents` is the real lever, and it costs time and money per run
- **Measured funnel**: 77 usable sold rows metro-wide -> 1-5 within 2 miles of a subject -> 0-3 after the sqft band
- **Only 1 of 5 listings got an estimate** — and age filtering removed nothing, so recency is not the constraint
- **A quarter of the pull was rentals** — 26 of 103 rows were leases, excluded correctly but paid for
- **Scaling estimate**: roughly 5% of agent-sourced sold rows land within 2 miles, so 3+ comps per subject needs ~800 rows, about $3.20 per pull, cached a week
- ? **targeted sold pulls** — test whether the actor's `startUrls` accepts a HAR sold search filtered by zip; geography-first would beat agent-crawling by roughly 5x on cost

> **Why not just widen the band**
> A comp that is half the subject's size is not a comp, and loosening the band to manufacture
> an estimate makes the KPI confidently wrong — the one failure mode this product cannot
> afford, since the whole point is to validate a price. Thin coverage that says "no estimate"
> is honest. The fix is more sold rows, not looser rules.

- **Four-mile sold tier added** — measured, not guessed: coverage went from 1 of 5 listings to 4 of 5
- **Confidence caps at low past two miles** — a wider comp is still an estimate, visibly a weaker one
- **Pipeline radius is now derived from the tier list** — it had a second hardcoded 2.0 that silently disabled any wider tier
- **Townhouses still uncovered** — only 4 same-type sold rows in 103; that is type scarcity, and only more rows fix it

> **Why the four-mile tier alone did nothing at first**
> The pipeline pre-filters sold history by radius before comp selection runs, so selection
> can only choose from what it was handed. A tier reaching four miles against a pool already
> cut at two is dead code that raises no error and returns no warning — the run just keeps
> saying "no estimate". Two radius constants in two modules will always drift; the pipeline
> now derives its own from the widest sold tier, and a test asserts the relationship.

- **Zip-targeted sold pulls do not work** — `listingType: sold` with a zip location returns zero rows; the actor finds sold history through the agent directory, and agents are indexed by city
- **`startUrls` documents for-sale and for-rent search pages only** — sold search is not among them, so geographic targeting of sold data is not available from this actor
- **Remaining levers for type scarcity**: crawl more agents (linear cost), or move to an MLS feed where sold data is queried by geography

> **Why this matters more than it looks**
> Sold comps are the difference between valuing a house against what neighbours asked and
> what they actually got. This actor can only reach them through agents' closed-deal history,
> which is scattered by construction — so comp density is bought by the row, not aimed. An
> MLS feed queries sold by geography directly, which is the strongest argument yet for
> Mohammad's answer mattering to the architecture and not just the budget.
