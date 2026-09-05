# HAR Data Recon — Findings

**Date:** 2026-09-04
**Question asked:** What can we actually get from har.com without an IDX feed, and what does that constrain?
**Answer in one line:** The public site is bot-walled and cannot be scraped directly, but two viable data paths exist — a licensed MLS API that HAR itself points at, and off-the-shelf managed scrapers that already return nearly every field the prospect asked for, including sold prices, AVMs, school ratings and GPS.

---

## 1. har.com is behind active bot protection — direct scraping is off the table

Verified by request, not assumed:

| Request | Result |
|---|---|
| `GET /robots.txt` | 200 OK |
| `GET sitemap.har.com/sitemap.xml` | 200 OK |
| `GET /homedetail/1501-montclair-dr-plano-tx-75075/25748` | **403** — `px-captcha` |
| `GET /homevalues/avm_detail?homeid=25748` | **403** — `px-captcha` |
| `GET /houston/about` | **403** — `px-captcha` |
| Real browser, homepage | Loaded fine |
| Real browser, two deep navigations | Session challenged: "Press & Hold to confirm you are a human" |

The site runs PerimeterX / HUMAN. Content pages return 403 to programmatic requests, and even a genuine browser session gets challenged after a couple of automated navigations. We did not attempt to defeat the challenge and won't — that's both a technical dead end and the wrong side of their Terms of Use.

**Consequence:** "just scrape the website," said plainly on the call, is not a thing we can build directly. Everything below is about how we get the same data legitimately.

## 2. What *is* openly published

`robots.txt` is short and permissive apart from a few paths — notably `Disallow: /tx`, `/tx/*`, `/search/flyer/*/avm`, `/social/`, `/track`. The sitemap host is wide open and reveals the whole content model:

- **363 sitemap files, 39 distinct types, ~49,900 URLs per shard.** Millions of URLs total.
- **For-sale inventory:** `forsale_sitemap_*` → `/homedetail/<address-slug>/<homeid>`
- **Sold inventory:** `sold_sitemap_*` → `/homedetail/<address-slug>/<homeid>?sid=<saleid>` — sold records are publicly indexed, with a distinct sale ID per transaction
- **Per-address AVM pages:** `avmdetails_*` → `/homevalues/avm_detail?homeid=<homeid>`, keyed on the same `homeid` as the listing page. HAR publishes its own automated valuation per property.
- **Geography:** `subdivisions_sitemap` (24,260), `neighborhoods_sitemap` (9,124), `zip_code_sitemap`, `county_`, `streets_`, plus `/pricetrends/<subdivision>-realestate/<id>` price-trend pages
- **Schools:** `school_sitemap` (22,824), `school_compare_`, `best_school_sitemap`

So the *shape* of the data we want is confirmed to exist and to be public-facing: listings, sold records, per-property valuations, subdivision price trends, school ratings. The sitemaps give us a complete URL universe and stable IDs. Only the page bodies are gated.

Also worth noting: HAR is no longer Houston-only. The homepage advertises **320,009 homes for sale and rent across Texas** — Houston, DFW, Austin, San Antonio. Scope is a choice now, not a limit.

## 3. Three ways to get the data, ranked

### Path A — Licensed MLS data (best data, needs credentials)

HAR has an exclusive data-licensing partner, **Repliers**, offering real-time MLS data over an API. Separately, HAR **members** get IDX tools and a data feed for roughly **$10/month** through `cms.har.com/idxtools/`.

- Complete, real-time, licensed, sold prices included, no anti-bot fight, no ToS exposure.
- **Requires the prospect (or a broker he works with) to be a HAR/MLS member.** This is the single question that most changes the product.
- Pricing beyond the member IDX fee is unpublished — Repliers is a commercial API, quote required.

### Path B — Managed scraping vendors (recommended default)

Two HAR-specific scrapers already exist on Apify and handle the PerimeterX problem as part of the service, including residential proxying. Between them they cover almost the entire requirement list.

| | `memo23/har-scraper` | `blackfalcondata/har-scraper` |
|---|---|---|
| Adoption | 33 users, 7 monthly, 5★ (1 review) | 2 users, 1 monthly, unrated |
| Price | ~$0.004 / property *(listing page and detail page disagree — verify)* | $0.0015 / property + $0.005 / run |
| **Sold price** | **`soldPrice`, `soldDate`, `soldPricePerSqft`** | `listingType: sold`, but no explicit sold-price field in the output schema |
| Valuations | `includeAvm` → appraisal-district value + AVM + $/sqft | `valuations[]` — multiple sources, each with `confidenceScore`, `marginOfError`, min/max |
| Native filters | Deep: beds, baths, sqft, $/sqft, lot, year built, HOA max, foreclosure, price-reduced, pool, property type, plus raw HAR params (`garage_num`) | Price only |
| Radius search | Via map-bounds URLs | Native `lat`/`lon`/`radiusKm`, stamps `distanceKm` on every result |
| Week-over-week diff | Not built in | **Built in** — `changeType`, `firstSeenAt`, `lastSeenAt`, `expiredAt`, repost detection |
| Detail depth | Moderate | Very deep: `rooms[]`, `schools[]` with `ratingLetter`, `features{}`, `taxInfo`, county, subdivision |
| Off-market lookup | **Yes** — search by street address, on or off market | No |

They are complementary, not redundant. Neither one alone covers everything.

### Path C — Build our own scraper

Would require defeating PerimeterX. Brittle, expensive to maintain, and squarely against HAR's Terms of Use. Not recommended, and not something we should offer to build.

## 4. Field coverage against what the prospect asked for

Every parameter named on the call, mapped to a real field:

| Asked for | Available? | Field |
|---|---|---|
| Bedrooms | Yes | `beds` |
| Bathrooms | Yes | `bathsFull`, `bathsHalf`, `bathsText` |
| Garage / car spaces | Partial — **verify** | `features["Garage Carport"]`, `features["Parking"]`, filterable via raw `garage_num`; the flat `garage` field looked null-typed |
| Square footage | Yes | `sqft` |
| Price per sqft | Yes | `pricePerSqft`, `avmPricePerSqft`, `soldPricePerSqft` |
| Area ("Spring") | Yes | `city`, `zip`, `subdivision`, `marketArea`, `county` |
| Duplex / half-duplex | Partial — **verify** | `propertyType` includes multi-family; whether HAR distinguishes half vs whole duplex needs checking |
| No HOA | Yes | `maintenanceFee`, filterable by max HOA fee |
| Age of house | Yes | `yearBuilt` |
| Nearby school rating | Yes | `schools[]` with `ratingLetter`, `ratingText`, `assigned` |
| Comps within a radius | Yes | `latitude`/`longitude` on every listing + native radius search + `distanceKm` |
| "What is this house worth" | Yes | `valuations[]` with confidence and margin of error, plus appraisal-district value |
| Weekly "what's new" | Yes | incremental mode with change classification and first/last-seen timestamps |
| Investor signals (bonus) | Yes | `daysOnMarket`, `hasPriceReduction`, foreclosure filter, `taxInfo`, `status` |

Effectively the entire requirement list is reachable. That is a better outcome than we expected going in.

## 5. The Texas sold-price catch

Texas is a **non-disclosure state** — sale prices are not in public county records. Sold prices exist only inside the MLS and wherever the MLS lets them surface.

`memo23`'s README says its sold data is aggregated from **agents' closed-deal history** on HAR. That works, but it means sold coverage is a **sample drawn from whichever agents we crawl** (`maxSoldAgents`, default 25), not a complete record of what sold in a given area.

**Why this matters for the KPI:** R2's "what is this house actually worth" is only as good as the comps behind it. Options, in order of quality:

1. Licensed feed (Path A) → complete sold data → real comps.
2. HAR's own published AVM per property → a valuation HAR already stands behind, with confidence bands. Cheap, consistent, but it's *their* model, not ours.
3. Agent-sourced sold sample → real closed prices, incomplete coverage.
4. Active-listing comps only → measures asking price, not clearing price. Weakest, and we should say so on screen if we ever fall back to it.

The good news: we can show **all** of them side by side — our comp-derived estimate, HAR's AVM with its confidence band, and the appraisal-district value — and let the disagreement between them *be* the signal. Three valuations that cluster is a confident number; three that scatter is a property worth a second look.

## 6. Cost, roughly

A weekly scan of ~3,000 listings in a target area, with full detail:

- `blackfalcondata`: ~**$4.50 / week** (~$20/month)
- `memo23`: ~**$12 / week** (~$52/month)
- Licensed HAR member IDX feed: **~$10 / month**, if he qualifies

None of these are a real cost. The decision is about data quality and legitimacy, not budget.

## 7. What this means for the build

- **Don't hardcode a vendor.** Put a thin data-source interface behind the MCP server, with adapters for each path. If he turns out to have MLS access, we swap the adapter and the product gets strictly better without a rewrite.
- **The similarity and comps math is ours, and it runs locally** on whatever rows the adapter returns. That part is vendor-independent and is where the actual product value sits.
- **Cache aggressively.** Every fetch costs money and time. Snapshots are already required by R3, so the cache and the week-over-week diff are the same mechanism.
- **Show the valuation spread, not a single number.** It's more honest and more useful than a lone estimate.

## 8. Questions this recon added or sharpened

New, and now the highest-priority ones:

- **Are you (or a broker you work with) a HAR/MLS member?** A yes unlocks the licensed feed at ~$10/month and makes every downstream number better. This is the first thing to ask.
- **Are you comfortable with a paid third-party data vendor** if the answer to the above is no? It's a few dollars a week, but it is a dependency and it should be a conscious choice.
- **How much does complete sold-price coverage matter to you** versus a good estimate? Path B gives a sample; Path A gives everything.
- **Houston only, or all of Texas?** HAR now covers the whole state. Wider scope costs more per run and changes what "nearby" means.
- **Would you accept HAR's own AVM as one input** to the KPI, shown alongside our own comp math?
- **Does "duplex vs half-duplex" need to be a hard distinction?** We need to confirm HAR exposes it before promising it.

Superseded from the original README: the assumption that comps might be limited to active asking prices. Sold prices are reachable — the open question is coverage, not existence.

## 9. Recommended next step

Spend about two cents running a 25-property live sample against a real target — Spring, TX, 3 bed / 2 bath — to confirm four things the schemas only imply: that sold prices actually come back populated, that garage count is retrievable, that duplex subtypes are distinguishable, and what HAR's AVM confidence bands look like in practice. Everything in this document is read from documentation and HTTP responses; a live sample turns it into fact before we design against it.

---

# 10. Live sample results — schemas turned into facts

Two runs against `memo23/har-scraper`, 2026-09-04:

- **For sale**, Spring TX, 3+ bed / 2+ bath, full detail + AVM → 25 records (`K531ZpQ9zdtgacNvK`)
- **Sold**, Spring TX, 10 agents crawled → 25 records (`agWPh3J54mWMZLde3`)

Cost: a few cents. Runtime: 28s and 37s. Both succeeded first try. *(Unnamed Apify datasets expire after about a week — re-run for pennies if the IDs are dead.)*

## 10.1 Resolved: garage, schools, HOA, taxes, sold prices

| Open question | Answer | Evidence |
|---|---|---|
| Garage count retrievable? | **Yes**, as text needing a parse | `"3 Attached"`, `"2 Attached ,Oversized ,Tandem"`, `"2 Detached ,Oversized"` |
| School rating available? | **Yes, and better than expected** — per level, letter + label | `schools.E.rating_letter: "A"` / `rating_text: "Excellent"`, plus separate M and S ratings |
| HOA detectable? | **Yes**, as text; null appears to mean none | `"$1075 Annually"`, `"$325 Monthly"`, `null` |
| Sold prices real? | **Yes** | `soldPrice: 460000`, `soldDate: "2026-08-27"`, `soldPricePerSqft: 147.91` |
| Tax data? | **Yes**, unasked-for bonus | `tax_rate: 2.4836`, `tax_year: "2025"`, plus appraisal-value history |

Sample for-sale record, trimmed:

```
31424 Creekside Oaks Ln, Spring 77386 · Falls at Imperial Oaks
$1,100,000 · $284.75/sqft · 4bd/4.1ba · 3,863 sqft · built 2020 · 3 Attached garage
HOA $1075 Annually · lot 13,987 sqft · 1 story · pool · DOM 1 · Coming Soon
30.143034, -95.393143 · tax rate 2.4836 (2025)
Schools: Kaufman Elementary A "Excellent" / Middle B / High B
Appraisal-district value $1.0M ($258.9/sqft)
```

Every single parameter from the call is in that one record.

## 10.2 The KPI already half-exists in the data

Two spreads fall out of the sample with no modeling at all:

**List price vs. appraisal-district value** (for-sale records):

| Property | List | District value | Spread |
|---|---|---|---|
| 22307 Roseville Dr | $220,000 | $174,000 | **+26%** |
| 21418 Avalon Queen Dr | $390,000 | $352,000 | +11% |
| 5519 Lynngate Dr | $215,000 | $205,000 | +5% |

**List price vs. actual sold price** (sold records):

| Property | Listed | Sold | Delta |
|---|---|---|---|
| 2322 Shadow Glen | $475,000 | $400,000 | **−16%** |
| 27318 Pendleton Trace | $470,000 | $460,000 | −2% |
| 3530 Azalea Sands | $360,000 | $375,000 | **+4%** |
| 4710 Walnut Willow Ct | $358,000 | $366,000 | +2% |

That second table is the most valuable thing in this whole recon. A **subdivision-level list-to-sold ratio** tells the prospect how much room there is to negotiate in a given neighborhood — and it's computable from data we can already reach. Nothing in the original brief asked for it, and it's arguably a better KPI than the one he described.

## 10.3 Three data-quality traps we now know to handle

**1. Rentals are mixed into "sold" results.** Six of the 25 sold records are leases:

```
3502 Gambel Dr   soldPrice 4000   soldPricePerSqft 1.22   status "Rented"
2558 Marufo Vega soldPrice 2500   soldPricePerSqft 1.19   status "Rented"
```

They must be filtered on `status == "Sold"`. There's a second, nastier tell: rental records use `propertyType: "Single Family"` while sale records use `"Single-Family"` — **a hyphen is the only difference.** Anything matching on property type has to normalize for this or it will silently mix leases into comps and destroy the KPI.

**2. Sold search ignores geography.** We searched Spring; we got back Houston 77095, Cypress, Conroe, Magnolia, New Caney and Cleveland. This confirms the mechanism — sold data comes from *agents' closed-deal history*, so it returns whatever those agents sold, wherever they sold it. **We have to geo-filter after the fetch**, and we should crawl more agents than the default to get usable density in one subdivision.

**3. Source data contains outright errors.** `2322 Shadow Glen` reports **10 bedrooms** on 4,507 sqft. That's a bad MLS entry, not a mansion. Comps math needs outlier guards, or one typo drags a whole neighborhood's estimate.

## 10.4 The AVM is weaker than the docs implied

The valuation that came back is `avmSource: "Appraisal Districts"` — the county tax assessment, not a market AVM. Worse, it arrives **pre-rounded as a string**: `"$1.0M"`, `"$352K"`, `"$205K"`. `"$1.0M"` could be anything from $1,000,000 to $1,099,999.

Two consequences:

- Appraisal-district value is a useful *reference point* — Texas assessments systematically lag market — but it is not a market valuation and shouldn't be presented as one.
- **Our own comp math has to be the primary estimate.** That's fine, and it's the honest design anyway. `blackfalcondata`'s `valuations[]` with real confidence scores and margins of error is worth testing as a second opinion.

## 10.5 Sold-comp density is the real constraint

Ten agents over five months yielded roughly **16 genuine sales across six cities**. For a defensible comp set in one subdivision we'd want a dozen recent sales within a mile. That means crawling far more agents per run, caching sold history aggressively across runs, and being upfront in the UI when a KPI rests on thin evidence.

This is the strongest argument for asking about MLS membership first. A licensed feed makes this problem disappear entirely.

## 10.6 What changes in the build

- **Parsers are a real component, not a footnote.** Garage text, HOA fee text, lot size (`"1.1 acre(s)"` vs `"13,987 sqft"`), abbreviated dollar strings — each needs a tested parser.
- **A normalization layer sits between vendor and math**, absorbing the hyphen trap, the rental bleed, and the outliers.
- **Sold history accumulates locally.** Each run adds to a growing comp database rather than being thrown away — this fixes density over time and cuts cost.
- **Every KPI ships with its evidence count.** "Estimated $312K, based on 4 comps" is honest. A number alone is not.
- **Still unresolved:** no duplex or half-duplex appeared in the sample, so we can't yet confirm HAR distinguishes them. Needs a targeted multi-family run before we promise it.

---

# 11. Duplex check — resolved, and it exposes a gap

Run: `sale`, Houston, `propertyTypes: ["multi-family"]`, full detail, 25 records (`eAhndOnm4KOjCxaSE`). 17s.

## 11.1 HAR does distinguish duplex — as a property subtype

Values seen in the sample:

- `Multi-Family - Duplex` (20 of 25)
- `Multi-Family - Fourplex`
- `Multi-Family - Multiple Detached Dw`
- `Multi-Family` (bare)

So "show me duplexes" is a clean, filterable query. That half of the question is a yes.

## 11.2 Whole vs. half duplex is **not** a field — it's in the address

There is no structured flag. The distinction shows up only as a unit designator in the address string:

| Address | Reading |
|---|---|
| `5013 Longmeadow St A/b` | Both units — whole duplex |
| `8445 Furray Rd A/b` | Both units — whole duplex |
| `214 E 32nd St C-d` | Both units — whole duplex |
| `7840 Nashville Unit A/b St` | Both units, malformed slug |
| `2116 Berry St` | No designator — ambiguous |
| `3204 Napoleon St` | No designator — ambiguous |

We can infer "whole duplex" from an `A/b`-style suffix with decent confidence, but "half duplex" is genuinely unresolvable from the flat fields — a bare address might be a whole building or a single side. If this distinction drives his buying decisions, it needs either the listing description parsed or a licensed feed where the MLS field exists.

**This is a specific thing to ask him at the demo**, because he raised whole-vs-half duplex unprompted on the call.

## 11.3 The real problem: multi-family listings carry no bed/bath data

Every one of the 25 records:

```
beds: 0    bathsFull: 0    garage: null    maintenanceFee: null
```

Not one populated bedroom count across the entire sample. His headline example was **"a 3-bedroom house... it should be a duplex, or half of a duplex."** Those two constraints cannot currently be combined on structured fields — the moment a listing is multi-family, the bedroom count goes to zero.

Consequences:

- **Similarity scoring must degrade gracefully.** A missing parameter has to be handled as *unknown*, not as *zero* — otherwise every duplex scores as a 0-bedroom house and ranks last. This is now a hard requirement on R1's scoring model, not a nicety.
- Bed/bath for multi-family likely lives in the free-text description. Extracting it is a parsing job with real error rates, and it's the one place where an LLM pass is genuinely the right tool.
- HOA and garage are equally unpopulated here, so "no HOA" on a duplex means *unknown*, not *none*.

## 11.4 More bad source rows, confirming the need for guards

- `9642 Intervale St` — listed at **$1,325** among for-sale duplexes. A rental that leaked into sale results, or a typo.
- `3415 Live Oak St` — $129,000, `sqft: null`, `lotSize: "0 sqft"`.

Second sample, second crop of nonsense rows. Sanity filters are not optional.

## 11.5 Market colour worth mentioning at the demo

Sixteen of the 25 have `yearBuilt: 2026` — Houston's duplex inventory is heavily new construction aimed at investors, clustered in 77051 / 77028 / 77033 / 77022, mostly $390K–$700K at $125–$210/sqft. That's a coherent investable segment, and the tool would be genuinely useful against it.

## 11.6 Updated open items

| Item | Status |
|---|---|
| Does HAR distinguish duplex? | **Resolved — yes**, as `Multi-Family - Duplex` |
| Whole vs. half duplex? | **Partly** — inferable from address suffix only; ask him how much it matters |
| Beds/baths on multi-family? | **Missing entirely** — scoring must treat absent as unknown; description parsing needed |
| Garage / HOA on multi-family? | Also absent — same treatment |
