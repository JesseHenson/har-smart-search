# HAR Smart Search — Requirements Draft

**Status:** Pre-build. Nothing implemented yet.
**Source:** Discovery call with Mohammad Hamzah (`meeting_saved_closed_caption.txt`).
**Target site:** https://www.har.com/ (Houston Association of Realtors).
**Purpose of this doc:** Pin down what we heard, state the assumptions we had to make to fill the gaps, and hand the prospect a short list of decisions only they can make.

---

## What we heard, in one line

An investor wants to point a tool at HAR listings, describe the deal he's looking for in loose terms, and get back a ranked shortlist where every result carries a "is this priced well?" number — and he wants to re-run that same search every week to see what's new.

---

## Requirements as we understand them

### R1 — Similarity search over HAR listings, not a hard filter

- **Variable input set.** The user supplies anywhere from 2 to 7+ parameters. Named on the call: bedrooms, bathrooms, garage spaces, square footage, price and price-per-square-foot, location/area (his example: "Spring"), property subtype (duplex, half-duplex, whole duplex), HOA / no-HOA, age of the house, nearby school rating.
- **Soft constraints, ranked output.** A boolean filter is explicitly *not* the goal. If a 4-bedroom matches on every other parameter, it should surface next to the requested 3-bedrooms. If inventory under a $200K ceiling is thin, listings somewhat above it should still appear rather than returning an empty set.
- **The score is a first-class output.** Each parameter contributes to a match score, and that score is shown as a number the user can sort and reason about — not hidden inside a black box.
- **Results are a snapshot in time.** Each run is timestamped and stored so runs can be compared to each other.
- **Worked example from the call:** 3 bed / 2 bath / 1-car garage / Spring / ~$120 per sq ft / duplex or half-duplex / no HOA.

### R2 — A per-listing valuation KPI derived from nearby comps

- **Every result gets a value estimate**, computed from comparable properties within a radius of that listing, using HAR data alone.
- **The KPI is the delta, expressed in the user's words:** "I'm paying $250K for that house, however very similar nearby houses go for $20K more / $20K less."
- **Two uses, both stated on the call:** validating that a search was any good, and prioritizing/sorting the results that come back.
- **This is real computation, not model eyeballing.** Radius selection, comp eligibility, $/sq ft normalization, and adjustment for parameter differences all have to run deterministically in the server so the same inputs always produce the same number.

### R3 — A repeatable weekly scan with a dashboard, shipped as a one-click install

- **Saved searches.** "These are the parameters for my next investment" — a named, re-runnable parameter set.
- **Week-over-week delta.** "Every week I can run that and say show me all the investments, everything that's come up." That means diffing this week's snapshot against the last: new listings, price cuts, gone-off-market.
- **Dashboard view** of ranked results, each result's KPI, and the comps behind that KPI, so the number can be audited rather than trusted blindly.
- **Packaged as an `.mcpb`** so the prospect installs it in one click with no developer setup, and drives it either from the dashboard or by asking in plain language.

---

## Shape of the build (draft, for discussion)

Three pieces inside one bundle:

| Piece | Job |
|---|---|
| **Retrieval** | Pull HAR listing data for an area, normalize it, cache it, timestamp it as a snapshot. |
| **Compute** | Similarity scoring and comps/valuation math. Deterministic, testable, no LLM in the arithmetic path. |
| **Dashboard** | Ranked results, KPI per listing, drill-down into the comps, saved searches, week-over-week diff. |

The LLM's job is translating "3 bed, 2 bath, Spring, no HOA, around $120/sqft" into structured parameters and explaining results in plain language. It should never be the thing doing the math.

---

## Assumptions we made — flag every one of these at the demo

We had to assume something to build a demo. Each of these is a real fork in the road, and a different answer changes the product.

1. **Geography is the Houston metro (HAR's coverage area).** Areas are named the way the call named them ("Spring") — city / neighborhood / subdivision names rather than drawn map polygons or ZIP codes.
2. **Listings are active for-sale residential**, including small multifamily (duplex), as the call's example implies. Not land, not commercial, not rentals.
3. **Comps come from HAR data alone**, because the call said so explicitly. If sold-price history isn't reachable, comps are built from *currently listed* nearby properties, which measures asking price, not market-clearing price.
4. **The KPI is expressed both ways:** a dollar delta and a percentage vs. estimated value, so it sorts cleanly.
5. **Similarity weights ship with sensible defaults** (location and budget weighted heaviest) and are adjustable, rather than being learned from behavior.
6. **Single user, running locally**, with snapshots stored on their machine. Not a multi-seat hosted product in v1.
7. **The weekly run is user-triggered or locally scheduled**, and the delta is shown in the dashboard rather than emailed or texted.
8. **"Value of the house" is a modeled estimate with a stated confidence**, not an appraisal, and the product will say so on screen.

---

## Open questions for the prospect

Grouped so they can be walked through quickly on the call.

### Data and access

- **Do you have Repliers access through your HAR membership, and what does it cost you?** This is now the decisive question, and it is sharper than it was when this document was written. HAR licenses its data exclusively through Repliers, whose production API starts at **$199/month**. Their free preview tier serves *sample* data, not the Houston market, so it cannot drive a real search. The partnership announcement says HAR adds its proprietary datasets to Repliers "at no cost to subscribers" — but that is about the datasets, not about API access, so the subscription question is genuinely open.

  For comparison, the managed-scraper path the tool ships with today costs roughly **$20–50/month** and returns real Spring listings. So switching to the licensed feed is a four-to-tenfold cost increase, bought with completeness, real-time freshness and zero terms-of-use exposure. That is a judgement only you can make, and the answer decides which adapter we finish.
- **Do you need sold/closed prices, or are active asking prices enough?** Real comps normally lean on recent *sold* data. If that's not accessible, the KPI measures "priced vs. the neighbors' asking prices," which is a different and weaker claim.
- **How fresh does the data need to be?** Live on every query, refreshed nightly, or refreshed weekly ahead of your scan?
- **Are school ratings sourced from HAR, or should we pull a third-party rating?** Third-party ratings carry their own licensing.

### Comps and the valuation KPI

- **What's your own definition of a comp?** Radius (half mile, one mile, same subdivision), time window for sold data (90 days, 180 days), and how tight the property has to match on size, age, and type.
- **How many comps make a number you'd trust,** and what should we show when there aren't enough?
- **Which adjustments matter to you?** Straight $/sq ft is the simple version. Adjusting for bed/bath count, lot size, age, condition, and garage is the serious version — but each one needs a rule you agree with.
- **Do you want to see the comps themselves,** or only the resulting number?

### Search behavior

- **Which parameters are hard limits and which are flexible?** The call was clear that beds and price should flex. Is location ever allowed to flex? Is there a max budget that never flexes?
- **How far should a result be allowed to stray before you'd rather see nothing?** 10% over budget is useful; 60% over is noise.
- **How many results per run** — a top 5, a top 25, everything above a score threshold?
- **Do you want a written explanation per result** ("included despite 4 bedrooms because price/sqft and area match"), or just the score?

### Workflow and output

- **Where do you want to work — a dashboard, or conversation?** The bundle can do both. Which one is the thing you open on a Monday morning?
- **How many saved searches do you expect to run** — one investment thesis, or several in parallel across different areas?
- **Do you want to be told when something new appears,** or is opening the dashboard weekly enough?
- **Do results need to leave the tool** — export to Excel/CSV, share with a partner, feed into an existing spreadsheet model?
- **Is this just you, or do others need access?** Answering "others" turns this from a local tool into a hosted product.

### Scope beyond v1

- **Do you want investment math on top of the KPI?** Rent estimate, cap rate, cash-on-cash, rehab budget, ARV. The call says "my next investment" — if that's where this is heading, it changes what data we need from day one.
- **Do distress and timing signals matter** — days on market, price-cut history, foreclosure or auction status?
- **Is your goal "find deals" or "value a specific property"?** The tool can do both, but they lead to different default screens.

---

## Explicitly out of scope for v1

Named here so nobody assumes them into the demo: no offer or transaction workflow, no CRM or lead management, no client-facing portal, no mobile app, no automated outreach to listing agents, no rental-market or property-management features.
