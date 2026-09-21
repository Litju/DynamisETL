# RES-108 — Root causes and solutions

**Date:** 2026-09-20
**Companion:** [STATUS.md](./STATUS.md)

The RES-108 screenshot audit concluded that *"analytical capability exists in code, but the
product does not visibly present analysis as the primary experience."* That is accurate but
understates the position. Running the product against the real local data showed that the
capability largely **did not execute**. Nine defects are recorded below. Six of them
independently prevented a flagship renderer from drawing anything.

Each entry gives the observed symptom, the actual cause, the evidence, and what was done.

---

## D1 — No ECharts chart rendered anywhere

**Symptom.** The Signals surface reported "1,346 source rows → 1,346 returned · exact samples
in this window", sized its container to 899 × 816 px, and drew nothing. The chart area was
blank on every route that used a chart.

**Evidence.** Browser console:

```
Uncaught (in promise) TypeError: Cannot read properties of undefined (reading 'isDisposed')
  at EChart.tsx:54
```

The DOM contained the ECharts root `<div>` at the correct size with **no `<canvas>` child** —
the engine initialised but never painted.

**Root cause.** In `EChart.tsx`:

```ts
const onAction = chart.on as (event: string, handler: () => void) => void;
onAction("dataZoom", handler);
```

`chart.on` was read off the instance and invoked **detached**. ECharts guards `on` against a
disposed instance through `this`, so `this` was `undefined` and the call threw — before
`setOption` ever ran. Because the throw happened inside a `.then()`, it surfaced only as an
unhandled rejection rather than failing loudly.

A cast to a function type hid the mistake: it silenced the type error that unbinding a method
would otherwise have produced.

**Solution.** `chart.on.bind(chart)`, with a comment recording why the binding matters.

**Why it survived RES-101.** Every chart test mocks `echarts`, so the mock's `on` has no
`this` requirement. The bug was only reachable against the real engine.

---

## D2 — Every tracked player rendered off-screen

**Symptom.** The field laboratory reported "22 players · 23 extrapolated · ball extrapolated",
drew the pitch outline, and drew no entities.

**Root cause.** Two coordinate spaces were conflated. The Pixi `world` container carries the
metres→pixels transform, and `drawPitch` correctly draws in metres. But `drawEntities` called
`pitchToScreen`, which **already returns pixels**, and drew the result *inside that same
transformed container*. The transform applied twice: a player at pitch centre landed at
roughly `(offsetX · scale) + offsetX` ≈ 3,800 px, far outside the viewport.

**Solution.** Entities and trails moved to an **untransformed overlay** container, placed via
`pitchToScreen`. This also gives markers a constant on-screen size instead of markers that
grow with the zoom — the behaviour an analyst expects. `fitViewport` now fits the real
105 × 68 m pitch plus a margin rather than the magic numbers `120`/`80`.

---

## D3 — The Pixi surface never tracked its host

**Symptom.** Pitch geometry mis-scaled relative to entities even after D2.

**Evidence.** Measured live in the page:

```
host:   899 × 762
canvas: 517 × 742
```

**Root cause.** Two compounding problems. `app.init({ resizeTo: host })` moved the canvas
without the viewport, and the renderer is created *before* the workbench pane reaches its
final size — so the first `fitViewport` ran against a provisional box. `fitViewport` keeps an
existing scale **on purpose** (a reader's zoom must survive a resize), which meant the
provisional scale was frozen for the session while entities were placed from the host's real
dimensions.

**Solution.** `syncToHost()` resizes the renderer and refits the viewport together. A
`readerAdjusted` flag distinguishes "not yet fitted" from "the reader owns this viewport": a
resize refits until the reader zooms or pans, after which their viewport is preserved. "Reset
view" hands control back to the automatic fit.

---

## D4 — Pose could never fit a window, and would have merged subjects

**Symptom.** The pose laboratory showed *"This window is display-reduced. Landmark viewing
requires exact frames; narrow from_ns/to_ns so the window fits the point budget."* There was
no range a reader could choose that satisfied it.

**Root cause.** A SkillCorner pose artifact interleaves every observed subject on one time
axis: **21,418,095 rows across 23 subjects** for one period. The viewer requested a window
unscoped, so any span wide enough to be useful exceeded the 20,000-point budget and returned a
min/max envelope — which a landmark viewer cannot use, because a per-bucket extremum is not an
observed landmark.

Worse, had it rendered, `extractFrames` groups by time only. An unscoped window would have
**merged 23 subjects' landmarks into a single frame** and labelled it with whichever subject
appeared first.

**Solution.** `entity_id` on the dense window endpoint, scoping to `object_id` when the
artifact has one and `subject_id` otherwise. RES-101 §21 already lists entity among the dense
window parameters, so this is the contract being completed rather than extended.

| Request | Rows | Reduced |
|---|---:|---|
| 20 s, unscoped | ~230,000 | yes |
| 20 s, `entity_id=795530` | **10,005** | **no** |

Pose streams declare no subject of their own, so the viewer probes one second of the artifact,
reports who is **actually observed** and defaults to the first — never the session roster,
which would offer a subject the window holds no landmark for.

---

## D5 — Canonical time is signed; the stack rejected the sign

**Symptom.** White CMJ could not carry a durable playhead or range. A committed time
serialised and then failed to parse back, silently dropping on reload.

**Root cause.** White CMJ trials are aligned on the source-provided takeoff and run from
**−1.345 s to 0**. Two independent guards rejected that:

```ts
const DECIMAL_NS = /^\d+$/;                    // client: no sign accepted
from_ns: int | None = Query(default=None, ge=0)  # server: no negative bound
```

The flagship dataset of the flagship demo path uses the one form both layers forbade.

**Solution.** `/^-?\d+$/` on the client and the `ge=0` constraints removed on the window
endpoint, while still rejecting decimals, exponents and whitespace. Tests now pin the
corrected contract in both directions rather than the assumption the data disproves.

---

## D6 — The pose subject was displayed lying on its side

**Symptom.** After D4 was fixed, landmarks rendered as a small unreadable blob.

**Root cause.** The scene mapped source `x, y, z` straight onto the renderer's axes. But the
SkillCorner hybrid frame carries **x and y as pitch-plane metres and z as a
player-centroid-relative vertical**. The renderer's up axis was therefore the pitch's lateral
direction, and the default camera looked straight down the body's long axis.

**Solution.** `toViewerPoint` maps the centroid-relative vertical to screen-up and
re-expresses the cloud about its own planar centre.

This is a **display transform only**, and it is safe for a specific, checkable reason: the
processor behind every served pose metric declares

```
translation_invariance:            relative_vectors_only
absolute_height_interpretation:    none
parent_tree_created:               false
```

so its angles are computed from relative vectors and carry no absolute position or height to
preserve. The viewer states the axis mapping on screen and repeats that it claims no absolute
height or pitch position, alongside the existing hybrid-frame warning.

**Rejected alternative.** Leaving the axes raw and telling the reader to rotate the camera.
That would have been technically defensible and practically useless — the default view is what
a reviewer sees.

---

## D7 — Processor overlays never resolved

**Symptom.** The pose sidebar read *"none declared for this stream's processor revision"* for
every stream.

**Root cause.** The viewer resolved the processor and then asked the methodology endpoint for
it **by algorithm id**:

```ts
methodologyQuery("pose.translation_invariant_kinematics")   // → 404
```

That endpoint is keyed by **metric id**. Every lookup 404'd, `overlays` fell back to
`NO_OVERLAYS`, and the sidebar reported the absence as a property of the processor.

The processor in fact declares **6 analytical segments** (left/right thigh, left/right shank,
shoulder width, hip width) and **4 angles** (left/right knee, left/right hip).

**Solution.** Resolve through the first pose metric of the stream, which names the revision to
read. Segments and angle arcs now render.

**Note.** The failure mode is the dangerous kind: a silent 404 became a scientific-sounding
statement about the processor. A missing lookup should not be reportable as a declared
absence.

---

## D8 — A display-reduced window had no time axis

**Symptom.** The GNSS speed trace collapsed to a near-vertical line at the left edge, with
axis ticks repeating the same value.

**Root cause.** Display reduction groups rows into time buckets and returns `t_start_ns` and
`t_end_ns` — **there is no `t_rel_ns` column in a reduced window**. Both transports looked
only for `t_rel_ns`:

```ts
const time = row[TIME_COLUMN];   // undefined for every row
```

so `timeNs` stayed all-zero and every envelope point plotted at x = 0. This affected every
reduced signal view, which is every window wide enough to need reduction.

**Solution.** The time column resolves to the bucket start when the exact column is absent, and
the reduction bookkeeping columns (`__bucket`, `t_start_ns`, `t_end_ns`, `bucket_rows`) are
treated as structure rather than as plottable measures. The GNSS session's 7,638 s profile now
reads as a real match.

---

## D9 — A quantity with no observations was offered as though it existed

**Symptom.** White CMJ Signals opened on an empty "Ground reaction force" axis.

**Evidence.** Column-level inspection of the canonical artifact:

| Column | Non-null |
|---|---:|
| `force_x_n`, `force_y_n`, `force_z_n` | **0** |
| `moment_*`, `cop_*` | **0** |
| `force_z_body_weight_ratio` | **1,346** |

**Root cause.** The source publishes the full canonical force schema but records only the
body-weight-normalised vertical trace. The laboratory offered every schema column, defaulted to
the first, and drew an empty axis for a measurement that does not exist in this dataset.

**Solution.** `populatedMeasures` / `populatedBandPairs` filter to quantities the window
actually observed. White CMJ now opens on "Vertical force / body weight", whose peak of **2.82
matches the served `cmj.peak_body_weight_ratio` of 2.821**.

---

## D10 — Layout defects

**Overlapping table rows.** `DataTable` positions rows absolutely at `index * rowHeight`. A
two-line identity cell is taller than the 30 px default, so catalog rows **visibly overlapped**
their neighbours. Rows now clip, and the catalog sets a row height that fits its content.

**Blank pane reserving flagship width.** Before a selection the catalog's detail pane reserved
40% of the viewport to say nothing. The catalog now takes the full width until a dataset is
selected.

**Explorer trial rows.** Provider trial labels carry the full condition-and-index description
(`condition=arms; source_row=163; acc_takeoff_index=1181; …`) and wrapped into an unreadable
three-line block at explorer width. The id leads; the label follows as one clipped line with
the full text on hover.

---

## P1 — The control plane had no foreign-key indexes

**Symptom.** `/runs` never finished loading in a browser.

**Evidence.**

```sql
SELECT indexname FROM pg_indexes WHERE schemaname='dynamis';
```

returned primary keys and four unique constraints. Nothing else. Every query filtering on
`dataset_id`, `session_id`, `run_id`, `stream_id`, `subject_id` or a checksum was a sequential
scan.

**Measured before:**

| Endpoint | Time |
|---|---:|
| `GET /api/runs?limit=200` | **69.08 s** |
| `GET /api/runs?limit=50` | 9.70 s |
| `GET /api/catalog/datasets` | 2.71 s |

`/api/runs` computes a per-run metric count with a correlated subquery over `derived_metric`
(~77k rows). At `limit=200` that is 200 sequential scans of the largest table.

**Solution.** Migration `0005_serving_read_indexes` — 12 read-path indexes. Migration
`0006_metric_catalog_index` widens the derived-metric index to `(metric_id, dataset_id)` so
catalog discovery is an index-only scan; it replaces the narrower index rather than adding a
second, since `metric_id` remains the leading column.

**Measured after:**

| Endpoint | Before | After | Factor |
|---|---:|---:|---:|
| `GET /api/runs?limit=200` | 69.08 s | **0.047 s** | 1470× |
| `GET /api/catalog/datasets` | 2.71 s | **0.036 s** | 75× |
| `GET /api/metrics/definitions` | 0.49 s | **0.017 s** | 29× |

RES-108 permits investigating this latency but forbids denormalising the scientific
authorities to hide it. Indexes do neither: no column, constraint, uniqueness rule or
measurement semantic changed, and every table keeps exactly the rows and keys it had.

**A measurement trap worth recording.** `psql` timed the aggregate at 2.4 ms while Python
measured 490 ms for the same statement. Postgres elides an unused subquery output column, so
wrapping the query in `SELECT count(*)` skipped the `json_agg` entirely. Only selecting the
real rows measures the real cost.

---

## Cross-cutting observations

**Mocks concealed three of these.** D1 (detached `chart.on`), D2/D3 (Pixi coordinate and sizing
bugs) and D7 (wrong API key) are all invisible to a suite that mocks the renderer or the
endpoint. The tests were not wrong to mock — jsdom cannot rasterise — but a green suite was
never evidence that a renderer drew anything. RES-108's insistence that *"a passing backend,
loaded data and installed renderer libraries do not satisfy this gate"* is exactly right, and
this is the mechanism.

**Silent fallbacks became false statements.** D7 turned a 404 into "the processor declares no
overlays". D9 turned an all-null column into an empty axis. D8 turned a missing column into
every point at zero. In each case the code degraded quietly where it should have been unable
to make the claim at all.

**Type assertions hid a real error.** The cast in D1 silenced precisely the error that
unbinding a method should produce.

---

## Outstanding risks

**The existing e2e specs will fail.** `acceptance.spec.ts`, `a11y.spec.ts` and `visual.spec.ts`
assert selectors and copy on surfaces this work deliberately replaced. They will be updated to
the new contracts, with each changed assertion called out rather than quietly relaxed. Until
that runs, Playwright and axe coverage is unverified.

**Production build unverified.** Chunking and the "no heavy renderer on Catalog" guarantee have
not been re-measured since the new chart surfaces landed.

**Screenshot capture.** The in-session browser pane repeatedly collapses its emulated viewport
between calls, producing inconsistently scaled captures. The nine required acceptance
screenshots will be taken through Playwright at a fixed 1600 × 1000, which is deterministic and
is what RES-108 K specifies.
