# HAR Smart Search — Build Log

The decision record from the subagent-driven build of this branch: 14 tasks, 32 commits,
42 controller rulings. Every ruling states what it decided, why, and what it costs if wrong.

Preserved from the build workspace so the reasoning behind design decisions survives in git —
particularly the ones a customer will ask about, such as why budget is a soft constraint.

---

# SDD ledger — plan: docs/superpowers/plans/2026-09-04-har-smart-search.md

Spec: docs/superpowers/specs/2026-09-04-har-smart-search-design.md (read, binding authority)
Branch: har-smart-search, base commit 1b28659

## Setup rulings

Ruling: Work on branch `har-smart-search` in the main working directory rather than a
separate git worktree — repo was created this session, has no other work in flight, no
protected main history, and the user's source documents live here.
Cost if wrong: the user's working directory holds in-progress code; recoverable by
`git checkout main`.

Ruling: Controller performed `git init`, `.gitignore`, and the initial docs commit during
setup, because the ledger and workspace require a repo to exist. Task 1's implementer
skips those sub-steps.
Cost if wrong: none; `git init` is idempotent and `.gitignore` matches the plan verbatim
plus `lib/` and `.superpowers/`.

## Pre-flight conflict scan

### Cross-task: shared files and interfaces

| Producer | Consumer | Produces / consumes | Finding |
|---|---|---|---|
| T1 models.py | T2–T14 | every dataclass and enum | clean |
| T2 normalize.py (parsers) | T3 normalize.py (guards) | same file, T3 appends | clean — T3 lists the added imports explicitly |
| T4 scoring.py (primitives) | T5 scoring.py (aggregate) | same file, T5 appends | **T5's import line re-imports `PropertyType`, already imported by T4** — carry to dispatch |
| T6 comps.py (cascade) | T7 comps.py (valuation) | `select_comps`, `MIN_COMPS_FOR_ESTIMATE` | clean |
| T6 comps.py | T9 db.py | `haversine_miles` | clean — T6 precedes T9 |
| T3, T5, T7, T9 | T11 pipeline.py | `normalize_listing`, `normalize_sale`, `score_listing`, `value_listing`, `Database` | clean |
| T13 web/app.py | T12 server/__main__.py | `ensure_dashboard_running(port) -> str` | **CONFLICT: T12 imports from T13 but is numbered first** |
| T8 diff.py | T12, T13 | `diff_snapshots` | clean |
| T9 db.py | T12, T13 | `get_scored_rows` returns valuation as a **dict**; T11 returns `Valuation` **objects** | clean — T12 handles both surfaces correctly (`build_search_response` attributes, `build_explain_response` dict keys) |
| T10 sources | T11, T12 | `ApifyMemo23Source.fetch_for_sale/fetch_sold` | clean |
| T5 Criteria.property_types (enum-value strings) | T10 `_TYPE_TO_ACTOR` | "duplex", "single_family", … | clean — both key on `PropertyType` values |
| T12 server entry point | T14 manifest.json | `src/har_search/server/__main__.py` | clean |

### Per-task self-consistency

| Task | Tests vs code it specifies | Finding |
|---|---|---|
| 1 | dataclass defaults vs assertions | clean (money-range assertion corrected in plan self-review) |
| 2 | parser inputs are verbatim recon strings | clean (truncation rule for `parse_money_abbrev` corrected in plan self-review) |
| 3 | guard fixtures vs guard rules | clean — `_positive_or_none(0) -> None` satisfies the multi-family zero-beds test |
| 4 | score tables vs tau constants | clean — verified numerically: beds 4→0.852, 2→0.402; +10%→0.719, +25%→0.291; geo 1mi→0.90, 3mi→0.50 |
| 5 | weighted mean vs coverage assertions | clean — verified: duplex case scores 1.0 at coverage 6/10.5 = 0.571 |
| 6 | tier matching vs fixtures | clean — verified: 0.02° lon at lat 30 = 1.198 mi, matches the 1.1–1.3 assertion |
| 7 | trimmed median vs outlier fixture | clean — 7 values, drop 1 each end, median 150/sqft holds |
| 8 | diff classification | clean |
| 9 | 34-column INSERT vs 34-value tuple; 18 vs 18 | clean — both counted |
| 10 | stub HTTP client vs adapter calls | clean |
| 11 | fixture counts vs assertions | clean — 3 fixture rows, 1 excluded, 2 scored |
| 12 | pure response builders vs assertions | clean |
| 13 | template output vs string assertions | clean (missing `index.html` in the file list corrected in plan self-review) |
| 14 | manifest keys vs assertions | clean |

### Rulings on scan findings

Ruling: **Execute Task 13 before Task 12.** Task 12 imports `ensure_dashboard_running`
from Task 13's module, so the numeric order cannot run green. Execution order is
1,2,3,4,5,6,7,8,9,10,11,13,12,14. The plan's own "Task Order Note" anticipates this.
Cost if wrong: none — no other task depends on 12 preceding 13.

Ruling: Task 5's import line duplicates `PropertyType` from Task 4. The implementer
merges the two import statements rather than adding a second one. Carried in the Task 5
dispatch.
Cost if wrong: a redundant import; harmless.

Ruling: `TAU["max_age_years"]` is defined in Task 4 but Task 5 scores age through
`ceiling_score`, not `target_score`, so the entry is unused. Leave it — removing it would
contradict the plan's Task 4 code block, and an unused constant is not a defect worth a
plan deviation.
Cost if wrong: one dead dict entry.

## Task log

### Task 1

Task 1: review — spec ✅, quality Approved. 1 Important (plan-mandated), 1 Minor, 1 ⚠️.

⚠️ resolved by controller: commit trailer. `git log -1 --format=%B 57d2268` shows
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` present. Not a gap.

Ruling: `HOA.monthly_usd: float` stands as written, and the Global Constraint has been
rewritten to say what it actually means. The "money is integer USD" rule exists to stop
float drift in figures that get differenced and compared — list price, sold price, comp
estimates. `HOA.monthly_usd` is a derived rate (an annual fee over twelve), never enters
valuation arithmetic, and is only used for a presence check in scoring (spec 5.2) and a
`${:.0f}/mo` display. Forcing it to int would break Task 2's asserted value
(`89.583`) and contradict Task 9's `hoa_monthly REAL` column — a three-task cascade for
no functional gain. The plan's constraint now reads: prices and valuations are integer
USD; derived rates (`HOA.monthly_usd`, `price_per_sqft`, `tax_rate`) are floats.
Cost if wrong: if HOA ever enters comp arithmetic, float money would be in that path.
Comps math never touches HOA today.

Task 1: minor (deferred): `uv.lock` committed though the brief's `git add` list predates
the uv-init fallback and does not name it. Correct call for reproducibility; noted for
the final review.

Task 1: complete (commits 1b28659..57d2268, review clean)

### Task 2

Task 2: review — spec ✅, quality Approved. 1 Important (plan-mandated), 3 Minor, 1 ⚠️.

⚠️ resolved by controller: reviewer could not confirm the "29 passed" full-suite figure
from a diff containing only Task 2's tests. 6 Task-1 tests + 23 Task-2 tests = 29. Arithmetic
checks out against Task 1's verified 6/6. Not a gap.

Ruling: FIX the Important finding, even though the plan mandates the code verbatim. The
fallback branch of `parse_money_abbrev` strips the decimal point along with separators, so
`"$425,000.00"` becomes 42,500,000 — a 100x inflation, not an imprecision. This module
exists precisely so bad source data cannot become a confidently wrong number, and a 100x
error on a valuation input is the worst possible expression of that failure. Observed
`avmValue` data is always abbreviated, so the path is unlikely today, but the fix is one
function and one test. The spec is the binding authority and its normalization contract
(4.1, 4.2) outranks the plan's transcription of a flawed branch.
Cost if wrong: a few lines of deviation from the plan's literal code, in a direction the
spec already requires.

Task 2: minor (deferred): `parse_garage` regex requires whitespace after the digit, so a
bare `"2"` returns None instead of GarageInfo(spaces=2, attached=None). No such shape in
observed data.
Task 2: minor (deferred): `parse_unit_designator` could false-positive on a hypothetical
`"N-S Fwy"` style fragment. No such shape in observed data.
Task 2: minor (deferred): `canon_property_type` PropertyType.OTHER fallback is untested.

Task 2: fix round 1/5 (1 addressed, 0 open — parse_money_abbrev decimal fallback corrected
and covered by 2 new tests; commits 48d671e..3232017)
Task 2: minor (deferred): fix introduced an uncaught OverflowError path — `float("inf")`
parses, then `round()` raises. One-word fix (`except (ValueError, OverflowError)`). Not
folded into Task 3 to keep task scopes clean; the vendor's avmValue field cannot produce
this shape. For final-review triage.
Task 2: complete (commits 57d2268..3232017, review clean)

### Task 3

Task 3: review — spec ✅, quality Approved. 3 Important (all plan-mandated), 4 Minor, 1 ⚠️.

⚠️ resolved by controller: reviewer declined to chase `Sale`/`Listing`/`NormalizeResult`
field definitions into unchanged `models.py`. Those were verified field-by-field in Task 1's
review (spec ✅, all 14 exports matched). `Sale` has no `flags` field by design — only
`Listing` carries flags. Not a gap.

Ruling: FIX all three Important findings, overriding the plan's verbatim code in each case.
They share one file and one fix round.

  1. `_positive_or_none` collapses a legitimate zero for `bathsHalf` and `daysOnMarket`.
     The helper exists because the vendor writes 0 to mean "not populated" for `beds` and
     `bathsFull` — a defect confirmed in scraped data. It was then applied to two fields
     where zero is the modal correct answer: most houses genuinely have no half-bath, and a
     listing put up today genuinely has 0 days on market. Conflating a real zero with
     unknown is the exact inverse of the error this module exists to prevent, so it stays
     wrong even though neither field feeds scoring or comps arithmetic today. Fix is a
     second helper that preserves zero.
  2. Price floor on `normalize_sale` has no test. One of the three guards is unprotected on
     half its code path — deleting the line would keep the suite green. The plan's test
     named `test_sale_priced_below_floor_is_excluded` calls `normalize_listing`, not
     `normalize_sale`.
  3. `_parse_date` catches `ValueError` but not `TypeError`, so a truthy non-string
     `soldDate` raises uncaught and aborts the whole batch. A defensive parsing layer that
     crashes on malformed input has failed at its one job.

Cost if wrong: three small deviations from the plan's literal code, each in the direction
the spec's normalization contract (4.1, 4.2) already requires.

Ruling: also tighten `_positive_or_none` to reject negatives while it is open (reviewer
Minor). The function's name promises positivity and currently returns -1 unchanged; the
fields it guards — beds, baths, sqft, year, prices — have no valid negative value.
Cost if wrong: negligible; folded into a change already being made to that function.

Task 3: minor (deferred): `test_school_rating_averages_available_levels` supplies all three
school levels, so the partial-availability branch is never exercised.
Task 3: minor (deferred): lease guard's `.strip().lower()` normalization is untested at the
boundary — no test uses `" rented "` or `"RENTED"`.
Task 3: minor (deferred): merged models import line is ~122 chars; check against a lint
line-length limit if one is added.

Task 3: fix round 1/5 (4 addressed, 0 open — `_int_or_none` added for bathsHalf and
daysOnMarket, sale-path floor test added, `_parse_date` catches TypeError,
`_positive_or_none` rejects negatives; commits 05c8686..64dbd1c)
Task 3: minor (deferred): `_int_or_none` passes negatives through unchanged
(`bathsHalf: -1` stays -1). Matches the fix spec as written; unaddressed edge case.
Task 3: complete (commits 3232017..64dbd1c, review clean)

### Task 4

Task 4: review — spec ✅, quality "Needs fixes". 1 Important (plan-mandated), 2 Minor, 1 ⚠️.
Reviewer independently recomputed every score-table value from the committed formula and
constants and confirmed all four tables to two decimals; constants unfudged.

⚠️ carried forward, not resolved here: reviewer could not confirm that `TAU` and
`DEFAULT_WEIGHTS` key names match the field names Task 5's aggregator looks up, since that
mapping lives in Task 5. Carried into Task 5's dispatch and its review as an explicit check.

Ruling: PARK the Important finding — `geo_score(False, None)` and
`categorical_score(None, ...)` returning 0.0 is NOT a defect in the system as designed, and
no fix round is warranted. The reviewer could not see Task 5 and reasoned that its weighted
aggregation would consume these worst-case scores and systematically under-rank listings
with missing data. It does not. Verified directly against the Task 5 brief: the aggregator
branches on unknown *before* ever calling either primitive — line 172 gates the `geo_score`
call behind `if subdivision_match or miles is not None`, and line 252 gates the
`categorical_score` call behind `if listing.property_type is None: ... else:`. The unknown
branches at lines 183 and 253 construct their params with `known=False`, which excludes them
from the weighted mean entirely and lowers the reported `coverage`. The 0.0 returns are
unreachable defensive defaults on paths the aggregator never takes.

The reviewer is nevertheless right that a bare 0.0 is a trap for any future direct caller.
Rather than spend a fix round on unreachable code, the mitigation rides along with Task 5,
which appends to the same file at zero extra dispatch cost: document the contract on both
primitives, and add the degenerate-path regression tests the reviewer's Minor asked for.
Task 5's review is instructed to verify the exclusion behaviour end-to-end — that is where
the real proof lives, in `test_unknown_parameters_are_excluded_from_the_mean_and_lower_coverage`.
Cost if wrong: if Task 5's aggregator turns out to call these primitives on unknown inputs
after all, listings with missing location or property type would silently rank last. Task 5's
review checks exactly this, so the error surfaces one task later at the latest.

Task 4: minor (deferred, folded into Task 5): degenerate paths (ceiling <= 0, tau <= 0,
miles None, actual None) have no regression tests.
Task 4: minor (deferred): `ceiling_score`/`target_score` type-hint USD parameters as float
rather than int. Harmless under Python's numeric tower.

Task 4: complete (commits 64dbd1c..f3cc43f, 1 parked)

### Task 5

Task 5: review — spec ✅, quality "Needs fixes". 2 Important (both plan-mandated), 2 Minor, 2 ⚠️.

PARKED FINDING FROM TASK 4 NOW CONFIRMED. The reviewer independently hand-traced the
committed code and verified every clause of the ruling: the `area` path constructs its
unknown param without calling `geo_score`; the property-type path calls `categorical_score`
only in the `else` of a `None` check; the weighted mean divides by known weight only;
`coverage` is known-over-total; and `no_hoa` treats a missing fee as unknown. The duplex
fixture traces to score 1.0 at coverage 6/10.5 = 0.571. The Task 4 ruling stands — no fix
was needed and none was spent.

⚠️ resolved by controller: `Criteria.must` names with no backing field never gate. This is
correct behaviour, not a gap. `must` defaults to `["area", "max_price"]`; if the user
supplies no `max_price`, no budget param is generated and there is nothing to enforce.
Gating on an unspecified constraint would reject every listing for failing a limit the user
never set.
⚠️ resolved by controller: full `Criteria` field enumeration. The 11 scoreable fields were
verified against `DEFAULT_WEIGHTS` in Task 1's review (spec ✅, all exports matched);
`must` and `weights` are control fields, not scoreable. Not a gap.

Ruling: FIX finding 1 — `no_hoa` hard-codes 0.0 for every known HOA regardless of amount.
A listing publishing a $0 maintenance fee is precisely what a `no_hoa` requester wants, and
it currently scores identically to a $500/mo HOA. Observed vendor data emits null or a
positive amount, so the path is rare, but the code as written is indefensible on reading and
the fix is one expression. `parse_hoa("$0 Annually")` does produce `HOA(0.0)`, so the case is
reachable.
Cost if wrong: a listing with a genuinely zero published fee scores well on a no-HOA
request. That is the desired behaviour.

Ruling: FIX finding 2 NARROWLY — extract a `_ceiling_param` helper mirroring the existing
`_target_param`, and nothing more. The two ceiling blocks are near-verbatim duplicates and
`_target_param` already establishes the pattern for the target family, so the asymmetry is
the defect. I am explicitly REJECTING the reviewer's larger suggestion of a declarative
table driving one loop over all nine criteria: that is a redesign of the product's core
scoring path for style, mid-plan, with Tasks 11 and 12 still to build on it. The narrow
extraction is fully covered by existing tests; the rewrite would not be.
Cost if wrong: `score_listing` stays a long function. It is readable and tested.

Task 5: minor (deferred): `if criteria.min_school_rating:` is a truthy check where the rest
of the function uses `is not None`. A 0.0 floor would be skipped. Meaningless value in
practice.
Task 5: minor (deferred): the `area` param's `subdivision_match` is an OR of subdivision,
city and zip matches, so a city-wide match scores identically to an exact subdivision match.
Verbatim from the plan and likely intentional — the perfect-match test relies on it. Design
note for the final review, not a defect.

Task 5: fix round 1/5 (2 addressed, 0 open — no_hoa now scores 1.0 for a published $0 fee and
0.0 for a positive one with known=True in both, unknown branch untouched; `_ceiling_param`
extracted and used for both ceiling params, no over-broad restructuring — re-reviewer
confirmed everything else in score_listing byte-for-byte unchanged; commits 06c7d1f..c56a8ec)
Task 5: minor (deferred, USER-VISIBLE — flag to final review as fix-before-demo): the
`_ceiling_param` unknown branch synthesizes its detail via
`f"no {name.replace('max_', '')}"`, so `max_price_per_sqft` now renders "no price_per_sqft"
with an underscore where the original read "no price per sqft". Appears in the dashboard
whenever a listing lacks price_per_sqft and the criteria set a $/sqft ceiling — a plausible
demo path, since the prospect's own example specifies $120/sqft.
Task 5: minor (deferred): `_ceiling_param`'s docstring claims it handles `max_age_years`,
which still uses its own inline block. Cosmetic.
Task 5: complete (commits f3cc43f..c56a8ec, review clean)

## Progress: 5 of 14 tasks complete

### Task 6

Task 6: review — spec ✅, quality Approved. 1 Important (plan-mandated), 4 Minor, 1 ⚠️.
Reviewer hand-traced tier ordering, basis-label integrity, subject self-exclusion, filter
degradation and haversine accuracy — all correct. Confirmed a "sold" basis can never be
returned alongside asking comps, because pool selection ties the label to a homogeneous list.

⚠️ resolved by controller: ran `uv run pytest -q` directly — 85 passed, matching the
implementer's claim.

Ruling: FIX the Important finding. The untested branch is `select_comps` returning the widest
non-empty result when no tier reaches TARGET_COMPS, and in this product that is not an edge
case — it is the common case. Texas is a non-disclosure state, sold prices come from agents'
closed-deal history, and RECON measured roughly 16 genuine sales across six cities from a ten
-agent crawl. Thin comps are the normal condition, so the branch that handles them is the one
that fires most often in production and is currently the only one with no test. Task 7's
valuation math is about to be built directly on its return value.
Cost if wrong: one extra test. Nothing.

Task 6: minor (deferred): `Valuation` imported but unused in comps.py — Task 7 uses it, so
this is deliberate groundwork rather than dead code.
Task 6: minor (deferred): `l` used as a loop variable in `_same_type_listings`.
Task 6: minor (deferred): `_same_type`/`_same_type_listings` and the two `Comp` mappers
duplicate structure across the `Sale`/`Listing` type split.
Task 6: minor (deferred): `sale.sold_price_per_sqft or ...` uses a truthy check where
`is None` would match the file's own unknown-handling ethos. A real $/sqft of exactly 0
cannot occur.

Task 6: fix round 1/5 (1 addressed, 0 open — fallback branch now covered by two tests;
re-reviewer hand-traced per-tier counts 0/2/4/0 and confirmed the test genuinely lands on
`return best, best_basis if best else "none"` rather than an early tier return, and that the
empty-cascade test covers the other half of the same line; comps.py untouched;
commits ccec956..a89e2ec)
Task 6: complete (commits c56a8ec..a89e2ec, review clean)

### Task 7

Task 7: review — spec ✅, quality Approved. 2 Important (both plan-mandated), 2 Minor, 1 ⚠️.
Reviewer confirmed the binding constants are untuned, every adjustment guards on `is not None`,
all divisions are protected, the insufficient-comps and missing-sqft paths terminate before any
arithmetic, and — critically — `delta_pct = (price - estimate) / estimate` has the correct sign,
so negative means asking below comps. An inverted KPI would have reversed the product's entire
recommendation.

⚠️ raised: reviewer could not confirm from this diff whether the planted-outlier Sale is
admitted by Task 6's tier matching, which changes the n that `trimmed_median` runs on in that
test. Moot after the fix below — the new discriminating tests call `trimmed_median` directly.

Ruling: FIX finding 2 — three tests are tautological and give the defensive logic zero real
coverage. `trimmed_median([100,145,150,155,900])` returns 150 whether or not trimming happens,
because the middle element of a 5-list is unaffected by the magnitude of the extremes. The
planted-outlier test has the same defect at n=7. And the bedroom-cap test uses a delta of
2 beds = 0.06, which never reaches the 0.09 cap, so `_clamp` could be deleted and it would
still pass. Trimming and capping exist specifically because real scraped data contains a house
reporting 10 bedrooms on 4,507 sqft — untested defensive code against known-bad input is the
worst kind to leave uncovered.
Cost if wrong: a few extra tests.

Ruling: FIX finding 1 — add an aggregate cap of ±15% on the summed adjustment factor. The four
per-adjustment caps stack to ±31.5% with nothing bounding the total, which on a $360K estimate
is ±$113K on a number an investor acts on. My reasoning for capping rather than parking: if a
property needs a 30% adjustment to resemble its comps, it is not comparable, and the arithmetic
is fiction wearing the costume of precision. 15% is deliberately generous — wider than any
single cap — so it binds only in the genuinely absurd case. This is squarely the spec's stated
philosophy of never presenting a confidently wrong number.
Cost if wrong: a subject legitimately needing more than a 15% adjustment gets an understated
correction. That case should be surfacing as thin/poor comps anyway, and the confidence label
and comp count already tell the user how much evidence stands behind the figure.

Task 7: minor (deferred): `if ... and comp_lot:` is a truthy check where beds/baths/year use
`is not None`. A known comp lot of exactly 0 would silently skip the lot adjustment.
Task 7: minor (deferred): `comp_basis=basis if comps else "none"` is redundant — `select_comps`
already returns "none" for an empty result.

Task 7: fix round 1/5 — aggregate cap added (AGGREGATE_ADJUSTMENT_CAP = 0.15) plus two
cap-binding tests; implementer returned DONE_WITH_CONCERNS refusing one instruction on
mathematical grounds. Commit b305fb7.

Ruling: THE IMPLEMENTER WAS RIGHT AND MY INSTRUCTION WAS WRONG. I asked for a
`trimmed_median` test where plain `median` and `trimmed_median` diverge. They demonstrated
that is impossible and declined to fabricate a passing-but-hollow test. I verified the claim
independently: 200,000 randomized trials produced zero divergences, and the index arithmetic
proves why — dropping k elements from each end shifts the median's index by exactly k, so for
odd n the same element is selected and for even n the same pair is averaged.

The consequence is larger than the test gap that surfaced it. The spec claimed trimming is
"what neutralizes source errors like the 10-bedroom, 4,507 sqft record." That is false. The
**median** neutralizes it; the trim contributes nothing. The behaviour was never wrong — a
median is outlier-robust by construction, which is exactly what the product needs — but the
documentation misattributed the mechanism, and a reader hardening this code later would have
protected the wrong line.

Ruling: correct the documentation, not the mathematics. I have already rewritten spec 6.2 to
name the median as the source of robustness and describe the trim honestly as a retained
guard that would matter only if the estimator became a mean. A fix round 2 corrects the same
claim in the `trimmed_median` docstring. The existing tests stay: they verify that a planted
$2,000,000 outlier does not move the estimate, which is a true and load-bearing property of
the code — the earlier reviewer was right that the test cannot fail if trimming is removed,
and now we know that is because removing trimming changes nothing.

Ruling: REJECTED switching the estimator to a trimmed mean, which would make the trim
meaningful and would use more of a thin comp set than a median does. It changes the product's
valuation numbers mid-execution on a call the spec did not sanction.
Cost if wrong: with 6 comps a median consults 2 values where a 10% trimmed mean would consult
4. On thin comp sets — the normal case in a non-disclosure state — that is a real loss of
information. Worth raising with the user as a post-demo estimator question.

Task 7: fix round 2/5 (all findings addressed, 0 open — re-reviewer demonstrated genuine
discrimination for each new test rather than asserting it: the individual-cap test yields
392,400 where an unclamped factor gives 532,800, and the aggregate-cap test yields 414,000
where an unclamped 0.315 gives 473,400. Existing tests confirmed unmoved (factors 0.06 and
0.0, both inside 0.15). Round 2 confirmed docstring-only — no behaviour or test change
smuggled in. commits 2bf7603..0523598)
Task 7: complete (commits a89e2ec..0523598, review clean)

## Progress: 7 of 14 tasks complete — all core math done and verified

### Task 8

Task 8: review — spec ✅, quality Approved. 1 Important (plan-mandated), 1 Minor, 1 ⚠️.
Reviewer hand-traced all three price-unknown combinations and confirmed none produces a
phantom movement; PRICE_CUT/PRICE_UP are not inverted; every id from either snapshot is
emitted exactly once; duplicate ids within a snapshot collapse rather than crash.

⚠️ noted, resolves at integration: whether Tasks 12 and 13 call `diff_snapshots` correctly is
outside this diff. Their own reviews cover it.

Ruling: FIX the Important finding, same reasoning as Task 6's fallback branch. The code is
correct by hand-trace, but the brief itself names the missing-price behaviour as "the one
detail that carries real weight" and the test file only asserts the symmetric `None -> None`
case. The asymmetric transitions — `None -> 200_000` and `200_000 -> None` — have no
regression test, so a future change coercing an unknown price to 0 would silently produce a
phantom PRICE_CUT and send someone chasing a deal that does not exist. That is precisely the
failure the brief warns about, and it is two tests.
Cost if wrong: two extra tests.

Task 8: minor (deferred): the four `ListingChange` constructions repeat their field lists;
could be a small local helper. Not worth it at 59 lines.

Task 8: fix round 1/5 (1 addressed, 0 open — two asymmetric transition tests added;
re-reviewer demonstrated discrimination: under coercion-to-zero the first would misclassify as
PRICE_UP and the second as PRICE_CUT, so both genuinely fail if the guard is removed. diff.py
untouched, 38 insertions to tests only; commits 7757890..671ba9e)
Task 8: complete (commits 0523598..671ba9e, review clean)

## Progress: 8 of 14 — all pure-logic modules done. Storage and I/O next.

### Task 9

Task 9: review — spec ✅ on interface, quality "Needs fixes". 2 Important (both plan-mandated),
4 Minor, 1 ⚠️. Reviewer independently counted 34/34 and 18/18 columns and spot-checked ordering
across the same-typed runs; confirmed `sales_near` does both the SQL box and the exact
haversine, that the box divisor stays generous to ~36°N, and that every value is parameterised.

⚠️ resolved by controller: `recent_snapshots` returns `exclusions_json` as a raw string rather
than decoding it, unlike the other JSON columns. Checked the consumers: Task 12's `whats_new`
uses `recent_snapshots` only for snapshot ids, and Task 13's run template renders
`snapshot.exclusions_json` directly as text. The raw string is what both want. Not a bug.

Ruling: FIX finding 1 — `first_seen` is destroyed on every re-upsert. `INSERT OR REPLACE` is a
delete-and-insert in SQLite, so the column is rewritten with `now()` each time. Task 11's
pipeline calls `upsert_sales` on every run for every sold row it fetches, which means
`first_seen` would permanently equal the date of the most recent scan and carry no information
at all. The column exists to record when a sale was first observed, and provenance is the point
of a table that accumulates forever. Fix with `ON CONFLICT(mls_number) DO UPDATE` preserving
`sold_history.first_seen`.
Cost if wrong: one SQL statement and a test.

Ruling: FIX finding 2 — `GarageInfo.attached` and `.tags` are silently dropped on round trip.
The schema persists only `garage_spaces`, so a listing written with `attached=True,
tags=("oversized","tandem")` reads back as `attached=None, tags=()`. I considered accepting this
under YAGNI, since nothing currently reads those fields — scoring uses `.spaces` alone. Two
things decide it the other way. First, a persistence layer that returns an object unequal to the
one it stored is defective regardless of who reads it today. Second, the prospect named garage
as a search parameter on the call and RECON found the source distinguishes
`"3 Attached ,Oversized ,Tandem"` from `"2 Detached"` — rendering "2-car attached" in the
dashboard is more useful to an investor than a bare number, and that option disappears if the
data never reaches storage.
Cost if wrong: two columns persisting data nothing reads yet.

Ruling: ACCEPT that `Listing.raw` is never persisted. The raw vendor payload is large, is
already re-fetchable, and storing it would bloat a database meant to accumulate for years.
Documenting the intent rather than changing behaviour.

Task 9: minor (deferred): `_valuation_to_json`'s `appraisal_district` re-derivation is dead code
— `asdict` already converts the nested `MoneyRange`.
Task 9: minor (deferred): no test places a sale inside the SQL bounding box but outside the
haversine circle, so the exact-distance step is not proven load-bearing.
Task 9: minor (deferred): `Database` has no `close()`/context manager and no rollback on a
partial failure mid-loop.

Task 9: fix round 1/5 (2 addressed, 0 open — `ON CONFLICT(mls_number) DO UPDATE` preserves
`first_seen` while refreshing all 16 other columns (re-reviewer enumerated the SET list against
the full 18 and confirmed nothing else was omitted); `garage_attached` and `garage_tags_json`
added, tri-state attached and tuple tags round-trip equal, absent garage reconstructs as None;
INSERT recounted at 36/36/36 with positional alignment confirmed; schema still idempotent;
commits fe5f3e8..6c786e6)
Task 9: note: the `first_seen` test monkeypatches the clock to two fixed timestamps rather than
relying on wall-clock advance, so it cannot pass by same-second coincidence. The reviewer also
honestly flagged that the second garage test (attached=None) does NOT discriminate against the
pre-fix code — pre-fix produced None coincidentally — and is a forward-guard only. The
implementer had disclosed this themselves rather than overclaiming.
Task 9: complete (commits 671ba9e..6c786e6, review clean)

## Progress: 9 of 14 — core + storage done.

### Task 10

Task 10: review — spec ❌ (one signature mismatch), quality "Needs fixes". 1 Important
(plan-mandated), 4 Minor, 1 ⚠️. Reviewer diffed all five files programmatically against the
brief's embedded code blocks — byte-identical. Confirmed the adapter does zero normalization,
that every test injects a stub so nothing touches the network, and that the fixtures preserve
every awkward real-world shape including the hyphen drift and the three bad rows.

Ruling: FIX finding 1 — the brief's Interfaces line promises
`ApifyMemo23Source(token, actor="memo23/har-scraper", http=None)` but its own Step 5 code omits
`actor` and hardcodes the path. Nothing calls it with `actor=` today, so this breaks nothing
yet. It is still worth fixing: RECON identified a second viable actor
(`blackfalcondata/har-scraper`) with complementary strengths — native radius search, built-in
incremental diffing, and valuations carrying confidence scores — and the entire reason this
layer is a protocol is vendor swappability. A hardcoded path means trying that vendor requires
editing source.
Cost if wrong: one constructor parameter nothing passes yet.

Ruling: FIX A DEFECT THE REVIEW DID NOT FIND. Following the reviewer's ⚠️ about dropped
criteria, I compared what the fetch layer sends against what the scoring layer intends, and
they contradict each other. `criteria_to_actor_input` sends `maxPrice = criteria.max_price` and
`minBeds = criteria.beds` as hard vendor-side bounds. But Task 5's `ceiling_score` deliberately
scores a listing 10% over budget at 0.72, and its own committed test
`test_slightly_over_budget_listing_still_appears` asserts a $215,000 listing must surface
against a $200,000 budget scoring above 0.6. In production that listing is never fetched, so
the tolerant tail can never fire. The investor's exact words on the call were "then you may
show me some houses above $200,000, if the search result is not there for below" — the product
would silently fail its headline requirement while every unit test stayed green, because no
test spans the fetch and scoring layers together.

Supporting evidence this is an oversight rather than a decision: `minSqft` is already widened
to `sqft * 0.75` in the same function. The plan author had the instinct for square footage and
did not carry it to price, beds or baths.

Fix: widen the vendor-side window to the range scoring can meaningfully rank — ceilings to
+25% (where `ceiling_score` returns 0.29) and target minimums down one unit (where
`target_score` returns 0.40), leaving `minSqft` as it is. Client-side scoring remains the
authority; the fetch bounds exist only to cap volume.
Cost if wrong: modestly more rows fetched per run, at roughly $0.004 per property. Against
that, the alternative is a similarity finder that cannot show the near-misses it was built to
find.

Task 10: ⚠️ resolved by the above: `no_hoa`, `garage_spaces`, `max_age_years` and
`min_school_rating` are correctly NOT pushed vendor-side. Hard-filtering on them would exclude
the near-misses the product exists to surface, and every one of them is scored softly with an
unknown-tolerant path. Intentional, now documented.

Task 10: minor (deferred): `_run` has no error-boundary coverage — no test for a non-2xx
response, timeout, or malformed body.
Task 10: minor (deferred): `int()` truncation on `maxPricePerSqft` and `minSqft` is undocumented.
Task 10: minor (deferred): the omit-unset test asserts only `minBeds` and `maxPrice`.
Task 10: minor (deferred): only one property-type mapping is exercised.

Task 10: fix round 1/5 (2 addressed, 0 open — `actor` parameter added with per-instance URL
derivation, default path confirmed byte-identical to the old constant; fetch window widened via
named constants CEILING_WIDEN_FACTOR = 1.25 and TARGET_MIN_STEPDOWN = 1. The re-reviewer
independently recomputed both scoring values from core/scoring.py rather than trusting the
comments — ceiling_score at +25% is 0.29 and target_score one unit under is 0.40, both
confirmed. Omit-unset guards verified line by line as intact, floor holds at 1, no
normalization crept into the adapter, fixtures untouched; commits bd9ca2b..a814055)
Task 10: note: the implementer honestly labelled its floor test as non-discriminating against
pre-fix code (pre-fix also produced 1) and framed it as a regression guard rather than
overclaiming. Second time an implementer has volunteered that distinction unprompted.
Task 10: minor (deferred): `maxPrice` is now a third `int()` truncation site, same category as
the already-deferred truncation minor.
Task 10: complete (commits 6c786e6..a814055, review clean)

## Progress: 10 of 14 — core, storage and the vendor seam done. Integration next.

### Task 11

Task 11: review — spec ✅, quality Approved. 2 Important (both plan-mandated, both efficiency),
2 Minor, 1 ⚠️. Reviewer hand-traced the five-step order and confirmed each step's placement is
load-bearing; verified the lease guard by tracing `normalize_sale`'s rejection through the
pipeline's `if sale is not None` check and confirming `upsert_sales` would raise on a bypass;
confirmed exclusion arithmetic is complete (every fetched row lands in exactly one bucket);
confirmed the missing-coordinate and no-centroid paths both degrade without raising.

⚠️ resolved by controller, and it revealed a third defect. The reviewer could not confirm the
real adapter's signatures match the pipeline's call shapes. I checked: they match — the adapter
declares `fetch_sold(self, area, agent_depth=25, limit=200)` and the pipeline calls
`fetch_sold(area=...)`. But `sources/base.py`'s `ListingSource` protocol declares
`fetch_sold(self, area: str, agent_depth: int, limit: int)` with **no defaults**, so the
protocol does not promise what the pipeline actually relies on. A second adapter implementing
the protocol literally would raise `TypeError` at the first call. This is precisely the seam
the protocol exists to protect, and the second vendor (blackfalcondata/har-scraper) is a
realistic near-term addition.

Ruling: FIX all three. (1) Batch the sold-history upsert — one commit instead of N, where N is
the fetch limit of 200 by default. (2) Hoist the comp-pool list out of the valuation loop; it
is rebuilt per listing and is quadratic, which at the ~3,000-listing weekly scan the spec
describes is roughly nine million element copies of avoidable work. The hoist is provably
behaviour-preserving because `comps_from_listings` already excludes the subject by
`listing_id`, verified both by this reviewer and by Task 6's own
`test_subject_itself_is_never_its_own_comp`. (3) Give the protocol the same defaults the
adapter has, so the contract matches what callers depend on.
Cost if wrong: (1) and (2) are behaviour-preserving and covered by existing tests. (3) widens a
protocol signature, which cannot break an existing implementation.

Task 11: minor (deferred): `assert valuation.confidence in {"high","medium","low",
"insufficient"}` is tautological — the field is a Literal of exactly those four values. The real
assertion is the dict lookup above it, which raises KeyError if a listing were skipped.
Task 11: minor (deferred): `scored.sort(...)` duplicates ordering the DB already applies via
`ORDER BY score DESC`; harmless, and needed because `result.scored` is returned directly.

Task 11: fix round 1/5 (3 addressed, 0 open — sold upsert batched with an empty-list guard and
the lease guard confirmed still between `normalize_sale` and accumulation; comp pool hoisted
once with an explanatory comment; protocol defaults added to `fetch_sold` with `fetch_for_sale`
untouched. Order of operations unchanged, test count stable at 133 with no test edited;
commits dae4709..d620cf3)
Task 11: complete (commits a814055..d620cf3, review clean)

## Progress: 11 of 14 — integration done end to end. UI and server remain.
## NEXT: Task 13 before Task 12, per the pre-flight ruling (12 imports from 13).

### Task 13 — BLOCKED then ruled

Task 13: implementer returned BLOCKED with no commit. It implemented the brief verbatim, hit 6
failures with `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in
that same thread`, produced an isolated repro, declined to patch either the app or the test to
force green, and reported three options. That is exactly the right behaviour on a plan defect.

Ruling: THE PLAN'S TEST IS THE DEFECTIVE SIDE, not the app and not the store. Verified against
the brief directly. `create_app` calls `db_factory()` inside each of its four route handlers, so
the design intends a fresh connection per request. The production factory in
`ensure_dashboard_running` does exactly that — it constructs a new `Database` on each call, which
lands on the handler's own thread and works. The brief's test instead passes `lambda: db`,
closing over a single instance built on the main thread, so Starlette's TestClient portal thread
touches a foreign connection. The test subverts the contract the signature advertises.

Fix: make the test factory construct a fresh `Database` against the same path per call, mirroring
production. Writes are committed on every store method, so a second connection reads them fine.

Ruling: REJECTED adding `check_same_thread=False` to `Database`, which was the implementer's
first listed option and the tempting one-line fix. Starlette runs sync route handlers in a
threadpool, so a shared connection could genuinely be used concurrently by two threads. That flag
does not make sqlite safe for that — it only removes the check that currently surfaces the
problem. It would convert a loud, immediate error into a rare corruption, which is strictly worse.
Cost if wrong: none identified. Per-request connections are the safe shape here.

Task 13: minor ELEVATED for the final review: per-request `Database()` construction opens a
connection per request and never closes it, because `Database` has no `close()` or context
manager (already logged as a deferred minor under Task 9). Harmless across a demo's few dozen
page loads; a real file-descriptor leak in a dashboard intended to run for weeks. Worth closing
before this is used in anger, and it is now load-bearing rather than cosmetic.

Task 13: review — spec ❌, quality "Needs fixes". 4 Important (all plan-mandated), 6 Minor, 1 ⚠️.
Reviewer verified `kpi_chip`'s sign against `comps.py`'s delta formula (negative = below comps =
favourable, not inverted), confirmed `beds`/`baths`/`days_on_market` use `is not none` so a
legitimate 0 renders as 0, confirmed no `|safe` anywhere so autoescaping holds, and confirmed the
threading fix was scoped exactly to the test fixture.

Ruling: FIX findings 1 and 4 TOGETHER, because fixing the encapsulation fixes the correctness bug
in the place it can be tested. The index page runs
`SELECT saved_search, MAX(id), MAX(run_at), MAX(item_count) ... GROUP BY saved_search`. `id` and
`run_at` are correlated because both rise with insertion, but `item_count` is not — if last
week's run returned 40 listings and this week's returns 12, the front page reports 40. A wrong
inventory count on the first screen of a tool built for deciding where to put money is not a
cosmetic bug. Separately, three of four route handlers reach into `Database._conn` and execute
raw SQL against a private attribute from another module. Moving those queries into `Database` as
public methods puts the latest-row-per-group query somewhere it can be written correctly and
covered by a store test, and removes the encapsulation breach in the same stroke.
Cost if wrong: three new public methods on a class that already has eight.

Ruling: FIX finding 2 — the TOCTOU race in `ensure_dashboard_running`. The check and the
assignment are not atomic, so two callers can each start a server and race to bind the port.
Task 12 calls this from both `search` and `open_dashboard`. MCP clients generally serialize tool
calls, so this is unlikely rather than impossible — and the fix is a module-level lock.
Cost if wrong: three lines.

Ruling: FIX finding 3 — coverage renders as a bare percentage with no denominator. This one
matters more than its severity suggests, because the coverage figure exists entirely to make an
honesty distinction: 0.92 computed from three of seven requested criteria is a different claim
from 0.92 computed from all seven. "57%" alone does not tell an investor 57% of what. Showing
"4 of 7 criteria" restores the distinction the number was invented to carry.
Cost if wrong: slightly busier table cell.

Ruling: FIX the ⚠️ as well. The listing page's per-criterion breakdown loop is never exercised —
the test fixture passes `params=[]`. That screen is the demo's climax, where a result is opened
to show why it ranked and what the comps say, so an untested render path there is the worst
place to have one.

Task 13: minor (deferred): unused `RedirectResponse` and `date` imports.
Task 13: minor (deferred): `exclusions_json` renders as raw JSON rather than humanized text.
Task 13: minor (deferred): `spread_flag`/`comp_basis` render raw Literal tokens
("Sources single_source.").
Task 13: minor (deferred): a missing snapshot on the listing route 404s with "No such listing".
Task 13: minor (deferred): no test exercises the `/run/{id}/diff` route at all.

Task 13: fix round 1/5 (5 addressed, 0 open). Re-reviewer verified the item-count test genuinely
discriminates — the old query returns item_count = MAX(40,12) = 40 where the test asserts 12, so
it fails against the old query and passes only against the new one. Confirmed no handler touches
`_conn`; all eight pre-existing Database methods untouched with the new three strictly appended;
`check_same_thread` absent from the diff and the file; the per-call test factory unchanged; the
lock covers check and set in one critical section with no deadlock path; and `criteria_counts`
cannot divide by zero on empty params. Accepted the implementer's rationale for adding no
live-thread concurrency test — a real port-binding race would be flaky, and the lock is
verifiable by inspection, which the re-reviewer did. commits 929952c..6e04090
Task 13: complete (commits d620cf3..6e04090, review clean)

## Progress: 12 of 14 — dashboard done. MCP server, then packaging.

### Task 12 — BLOCKED then ruled

Task 12: implementer returned BLOCKED with no commit. The brief's code imports
`mcp.server.fastmcp.FastMCP`, which does not exist in the installed `mcp` 2.x. It reported two
options rather than restructuring the server around a guess. Correct call, and the second time
this run that a blocker was handled properly instead of being forced green.

Ruling: PORT TO mcp 2.x. I inspected the installed package rather than deciding from memory, and
the port is two lines. `mcp.server.mcpserver.MCPServer` takes the same `name` constructor
argument, exposes the same `.tool()` decorator, and exposes `.run(transport='stdio')` with stdio
as the default — so every `@mcp.tool()` definition and the `main()` body carry over untouched.
Only the import line and the instantiation change.

Ruling: REJECTED pinning `mcp[cli]<2`, the implementer's other option. It would work, and on a
deadline it is the tempting choice, but it ships a brand-new product on a deprecated major from
day one, and the thing it buys — avoiding a port — turns out to cost two lines. The reason 2.x
was installed at all is that `pyproject.toml` declares `mcp[cli]>=1.2.0` with no upper bound, so
also constrain it to the major the code actually targets. An unbounded major is what let a
breaking change in silently.
Cost if wrong: if some part of the 2.x tool surface behaves differently in ways the two-line port
does not cover, it surfaces in this task's tests or at bundle load. Pinning remains available as
a fallback.

Note: the mcp package ships a deprecation shim at the old import path that raises a
ModuleNotFoundError naming the new class and linking the migration guide. That is why this was a
ten-minute diagnosis rather than an afternoon.

Task 12: review — spec ✅, quality Approved. 0 Critical, 0 Important, 3 Minor, 2 ⚠️.
Reviewer compared all 207 lines against the brief and confirmed the port was exactly two lines
with nothing else opportunistically "cleaned up"; verified the three builders are genuinely pure,
that no tool body recomputes a KPI, that the two deliberately-different valuation shapes were not
unified, that the missing-token error is actionable, and that module import has no side effects
so packaging can import it without a token set.

⚠️ carried into Task 14: whether `HAR_APIFY_TOKEN` / `HAR_DEFAULT_AREA` / `HAR_DASHBOARD_PORT` /
`HAR_DB_PATH` match the env var names the manifest supplies. Task 14 writes that manifest, so its
dispatch and review check the pairing explicitly.

Ruling: `config.default_area()` has zero call sites anywhere in the tree — DROP IT, along with the
matching `default_area` entry the plan's manifest would declare. A shipped settings control that
does nothing is a small lie to the user: the extension's configuration UI would offer a "default
area" field that changes no behaviour. I considered instead wiring it as a fallback for `search`'s
`area` argument, which would be genuinely useful, but that means making a required tool parameter
optional at the last minute and changing the schema the model reads. Not worth it on the eve of a
demo for a knob nobody has asked for. Easy to add later if the prospect wants it.
Cost if wrong: one small convenience feature absent. `search` still takes an explicit area, which
the model fills from the user's own words.

Task 12: minor (deferred): the module docstring still reads "FastMCP entrypoint" after the port.
One word, caused by my own ruling — for the final review's fix wave.
Task 12: minor (deferred): `comp_count` falls back to `0` rather than `None` when a valuation is
absent. Reviewer verified the branch is unreachable through the real pipeline, since `run_search`
writes a Valuation for every scored listing.
Task 12: minor (deferred): no test covers the `explain`-unknown-id, `whats_new`-single-snapshot,
or `price_up` branches. Correct by inspection; would need a fake Database to test at tool level.
Task 12: complete (commits 6e04090..7a967af, review clean)

## Progress: 13 of 14 — everything but packaging.

### Task 14

Task 14: review — spec ✅, quality Approved. 1 Important (plan-mandated), 2 Minor.
Reviewer confirmed on disk that the manifest's entry_point and args paths resolve to a real file,
that the declared tools list exactly matches the four `@mcp.tool()` registrations, that
`apify_token` is both sensitive and required, that the dashboard port default agrees between
manifest and config, that `PYTHONPATH` names the same `lib/` directory BUNDLE.md's build step
vendors into, and that BUNDLE.md quotes the space-containing path. It also verified every
dataclass field and signature `smoke_run.py` touches against the real source — no drift.

Ruling: FIX the Important finding. `tests/test_manifest.py` asserts only
`entry_point.endswith("server/__main__.py")` — a string suffix. It never checks the file exists,
and never cross-checks the declared tools against the ones the server registers. That is the same
pattern I have been correcting all run: a test that cannot fail for the reason it exists. Here it
guards the bundle's most consequential failure mode, because manifest drift does not break a test
or raise an error — the .mcpb installs cleanly, accepts the prospect's token, and then does
nothing. Two assertions close it.
Cost if wrong: two assertions.

Task 14: minor (deferred): the manifest repeats the entry-point path in both `entry_point` and
`args`; editing one without the other would let them diverge silently.
Task 14: minor (deferred): `smoke_run.py` writes `smoke.db` relative to the working directory, so
runs from different directories scatter database files. Harmless given BUNDLE.md tells the reader
to cd to the project root first.

Task 14: fix round 1/5 (1 addressed, 0 open — entry point now asserted to exist on disk resolved
against the repo root, and the declared tools cross-checked against `mcp.list_tools()` derived
from the code rather than a second hardcoded list. Implementer demonstrated both assertions by
inducing each failure and restoring the manifest byte-identically; re-reviewer confirmed the
import is inside the test function and has no load-time side effect. commits 56e84e2..92812b2)
Task 14: complete (commits 7a967af..92812b2, review clean)

## ALL 14 TASKS COMPLETE — 26 commits, 157 tests passing.

## FINAL WHOLE-BRANCH REVIEW

Verdict: merge with fixes; demo with fixes. 1 Critical, 8 Important, ~14 Minor, full triage of
all 44 deferred items into fix-before-demo / fix-before-real-use / can-stand.

CONTROLLER ERROR, CORRECTED. The Critical is mine. `Criteria.must` defaults to
`["area", "max_price"]`, and `score_listing` deletes any listing whose `must` parameter scores
below 0.5. `ceiling_score` crosses 0.5 at exactly +16% over budget. Verified by executing the
committed code: against a $200,000 budget, $220,000 scores 0.895, $232,000 scores 0.812, and
$235,000 / $250,000 / $300,000 are all DROPPED.

During Task 10 I widened the vendor fetch bound to 1.25x precisely so the tolerant tail could be
fetched, and I cited `test_slightly_over_budget_listing_still_appears` as evidence the tail
works. That test passes `must=["area"]` — it disables the very gate that still blocks production.
So does `scripts/smoke_run.py:35`. And `server/__main__.py` exposes no `must` parameter at all, so
the model cannot override the default. My evidence was invalid, and the widening I authorized
buys nothing above +16%: the $232k-$250k band is now fetched, paid for, and discarded before the
user ever sees it.

Root cause is in the spec, not the implementation. §5.2 advertises graceful decay to +50% as
rankable; §5.3 says budget is a hard constraint. Both cannot hold. The implementation faithfully
encoded the wrong one, and no test covers the default `must` at all.

Ruling: change `Criteria.must` to `["area"]`, correct spec §5.3 to match §5.2, and add scoring
coverage using the DEFAULT criteria rather than a gate-disabled one. Location stays hard; budget
is the single constraint this product exists to relax. Also adopt the reviewer's recommendation of
cross-layer requirement tests driven through `run_search` — every defect found in this build lives
in a seam, and the suite is organized by module.
Cost if wrong: results include listings materially over budget. They rank low, carry the KPI, and
the user sorts them away — which is the stated design.

Ruling: FIX WAVE covers Critical #1 plus Importants #2, #3, #4, #5 (as a labelling change, not a
refetch), #6, #7, the three raw-token strings that reach the demo screens, and `filterwarnings`.

Ruling: PARK #8 — the listing page has no comps table, which README names as the point
("so the number can be audited rather than trusted blindly"). This is a plan defect: the Task 13
brief contained no such table. It is new UI work rather than a code defect, `explain` already
returns the comps conversationally, and whether to build the screen before the demo is a product
call for the user rather than mine to make at the end of a build.
Ruling: PARK #9 — comp lookup requires coordinates on both sides, so spec §6.1's radius-free
tier-1 subdivision match cannot fire without them. Real, "before real use", and a design change to
the store's query surface that deserves its own cycle.

## FIX-WAVE RE-REVIEW

9 of 10 findings fully addressed and verified by independent trace, including the Critical.
Reviewer confirmed the lease guard still rejects before accumulation, that Fix 4's basis label
reports the weaker basis on a mixed set, that location remains hard, that the rewritten models
test asserts the corrected requirement both positively and negatively rather than weakening it,
and that requirement test 2 would have caught the Critical (it produces `scored == []`,
`dropped_by_must == 2` against the old default).

Finding 7 PARTIALLY addressed, plus one Minor. Adjudicated below. There is no second fix wave, so
these are targeted rulings rather than another pass.

Ruling: FIX the area-capitalization split. `core/keys.py` strips the display half of the snapshot
key but does not case-fold it, while the digest lowercases. Verified: `"Spring"`, `" spring "` and
`"SPRING"` with identical criteria yield `'Spring #a4ccfec1'`, `'spring #a4ccfec1'` and
`'SPRING #a4ccfec1'` — three buckets, one hash. `whats_new` then reports "only one snapshot
exists" or refuses as ambiguous between keys the user cannot tell apart. The model composes `area`
from free-form speech, so this is reachable in ordinary use, and it defeats R3 — a third of the
brief, and the exact requirement Fix 7 was made to protect. `tests/test_keys.py` compares only the
hash suffix, so its name claims a property the code does not have; that test is why this survived
the wave. One line plus an honest test.
Cost if wrong: none identified. Case-folding the display half cannot merge genuinely distinct
searches, because the digest still separates them.

Ruling: FIX the smoke script's demo path. `scripts/smoke_run.py` writes to `smoke.db` in the
working directory while the server reads `config.database_path()`, and it passes a hardcoded
`saved_search="spring-investment"` that bypasses the key derivation entirely. `BUNDLE.md`
documents that script as the pre-demo snapshot capture, so the documented procedure cannot produce
a diffable pair — the week-over-week beat would silently have nothing to show. It is also the same
"explicit argument hides the default under test" pattern that concealed the Critical.
Cost if wrong: the script writes to the real database rather than a scratch file, which is what
the demo needs.

Ruling: FIX the unreconciled exclusion footer. The run page prints a total that includes
`dropped_by_must` beside an itemization covering normalization exclusions only, so it reads
"3 rows left out — 1 row priced below the $10,000 sale floor" with two rows unnamed. Minor by
severity, but it sits on the demo's main screen under a "Data quality" heading in a product whose
stated rule is that every excluded row is named, and with budget now soft by default
`dropped_by_must` is non-zero on any live run containing out-of-area rows.
Cost if wrong: one more line of prose in a footer.

Ruling on the alternative: I rejected shipping these as demo caveats. The caveat list would have
been "type the area with identical capitalization both times, ignore the exclusion count because
it will not match its own list, and do not follow the documented pre-demo procedure because it
cannot work." Three landmines in a customer demo, against a few lines of change.

PARKED, unchanged: the listing page has no comps table (product call, `explain` covers it
conversationally); comp lookup requires coordinates so spec 6.1's radius-free tier-1 cannot fire;
`Sale.flags` is not persisted, though the guard's material effect does persist; `explain` returns
raw param `name` identifiers to the model; the results table shows a comp count without its basis;
`confidence_label` counts comps irrespective of basis.
