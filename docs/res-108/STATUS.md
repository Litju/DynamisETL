# RES-108 — Implementation status

**Issue:** [RES-108 — DynamisData 06B: Flagship UX/UI polish and analytical surface upgrade](https://linear.app/alignerr-cmj/issue/RES-108/dynamisdata-06b-flagship-uxui-polish-and-analytical-surface-upgrade)
**Branch:** `codex/res-108-dynamisdata-ui-finish` (single worktree)
**Baseline:** `e2834c3` (RES-101G, accepted)
**Date:** 2026-09-21
**State:** items 1–10 plus audit corrections D, E, F, K complete on the dedicated RES-108 branch.
**Ready for acceptance:** **Yes — full visual evidence set is ready for user review.** RES-108 remains In Progress.

---

## 1. Summary

RES-108 was scoped as a polish pass. It is not one.

Inspecting the running product against the real local data showed that **every flagship
renderer was non-functional**, for six independent reasons, none of them cosmetic. A chart
engine that threw before drawing, a pitch that placed players off-screen, a pose window that
could never fit its point budget, a time axis that rejected the sign the flagship dataset
actually uses, a 3D scene that laid the subject on its side, and processor overlays that
resolved through the wrong API key.

Polish applied on top of that would have been paint on an instrument that does not work. The
defects are documented in [ROOT-CAUSES.md](./ROOT-CAUSES.md); this file records what shipped,
what is verified, and what is left.

A separate finding: the control plane shipped with **no foreign-key indexes at all**. One
serving endpoint took **69 seconds**. That is addressed too, without denormalising any
scientific authority.

---

## 2. Commits

Ten atomic commits, one per completed item, in the order RES-108 specifies.

| Commit | Scope |
|---|---|
| `f9af801` | Index the serving read paths (migration 0005) |
| `7bd4c2d` | Item 1 — first impression and information architecture |
| `492b459` | Item 2 — deterministic real-data defaults |
| `0f034a5` | Item 3 — Signal Laboratory visual upgrade |
| `2ffac13` | Item 4 — 2D field laboratory polish |
| `5b37f65` | Item 5 — 3D biomechanics laboratory polish |
| `3b0e8d2` | Audit D — session Overview analytical summaries |
| `d4b1a8c` | Audit E — chart-first Compare (migration 0006) |
| `79e1dd7` | Item 6 / audit F — methodology, provenance and rights evidence |
| `267ba49` | Audit K — Quality and Runs as evidence surfaces |
| `16542fc` | Item 7 — typography, tokens and control-height consistency |
| `92dda4d` | Item 9 — fixed workstation validation at 1440×900 and 1600×1000 |
| `c9836e2` | Real-browser ECharts, Pixi and R3F smoke coverage; React Flow attribution fix |
| `b41d977` | Explicit right-handed pose display transform and proportional-bias guard |
| `0bd0a5a` | Item 8 — restrained tab motion with reduced-motion CSS equivalence |
| `c22dd5c` | Item 10 — acceptance, lazy-loading, accessibility and screenshot seal |

64 files changed, +8,363 / −1,661.

Audits D, E, F and K are binding correction items in RES-108 that do not map onto a single
numbered implementation item. They were committed separately rather than folded into a
neighbouring item, per the issue's instruction to split rather than combine unrelated work.

---

## 3. What is resolved

Each surface below was verified in a browser against the real local data, not against
fixtures.

### Catalog (audit C)

- Product header carrying the **real registered scale**, summed from the served catalog:
  5 datasets, 7 modalities, 122 sessions, 1,320 trials, 76,988 derived metrics.
- Dataset names readable at desktop width; provider on a second line.
- A **Laboratories** column stating which of Signals/Field/Pose each dataset can actually
  open. The gate is `stream_count`, not declared modality, so GymAware reads "metrics only"
  instead of advertising a Signals laboratory it has no canonical stream to render.
- Selecting a dataset yields versions, rights, sessions and direct laboratory entry actions
  for its supported surfaces only.

### Shell / information architecture (audit B, H)

- Shell regions are **earned per route** (`shellLayoutFor`). Explorer, inspector and transport
  exist only inside an open laboratory session. Elsewhere the inspector compacts to a 32 px
  rail and the transport is absent rather than disabled.
- The three simultaneous `NO DATA` panels are gone.
- The context bar is a readable spine: resolved dataset and session names lead, exact
  identifiers sit beneath them via `CopyableId`. `SURFACE catalog` is gone.

### Signals (audit A, J)

- Channels are grouped by physical quantity, each with its own axis, so a body-weight ratio
  never shares a scale with a moment in newton metres.
- White CMJ opens directly on the real force trace. **Peak 2.82 BW matches the served
  `cmj.peak_body_weight_ratio` of 2.821.**
- GNSS renders a real 7,638 s match profile with activity bursts, two gaps and sprint peaks
  near 8 m/s.
- Exact vs display-reduced is a badge with shape and text; the envelope is named a reduction
  envelope and captioned as display reduction, not measured uncertainty.
- A trial evidence pane carries the real derived metrics beside the trace.

### Field (audit J)

- Surveyed pitch geometry: 16.5 m penalty area, 5.5 m goal area, 9.15 m centre circle and
  penalty arc clipped to the area edge, 11 m penalty mark, corner arcs, goal frames.
- 22 players, the ball, and **6 real DFL source events** in a 17.3 s window.
- Entity labels with a stable collision rule; opaque provider ids shortened to their
  distinguishing segment (`DFL-OBJ-0037YC` → `0037YC`).
- Clicking a player commits `subject=DFL-OBJ-00028V` with halo, crosshair and read-out.
- Layer toggles for trails, labels and events; reset view.

### Pose (audit J)

- Upright figure, 29 landmarks, subject 11897.
- The processor's **6 declared segments and 4 declared angles** now render.
- Mean provider p90 predicted error radius 0.136 m, explicit and subordinate.
- Bounded local reference grid — never an infinite ground plane, which would invite height to
  be measured against it.
- Hybrid-frame warning plus an explicit axis-mapping note.

### Overview (audit D)

- Ranked bar chart of the session's headline metric, one bar per entity.
- Stacked speed-zone breakdown where the whole `locomotor.distance_zone` family is served.
- One attributable served value: *"Highest total locomotor distance 14454.5 m ·
  DFL-OBJ-00008F · highest of 55 served values"* — exactly one Gold row, so it keeps a method,
  a run and a provenance chain.
- Stream contracts collapsed but labelled; derived metrics table filterable with readable
  names first.

### Compare (audit E)

- **Unpaired**: box plot per group with a five-number summary table, stating that the box
  describes the values in view rather than a pipeline result.
- **Paired**: structural pairing on dataset, session, trial, subject and entity — stated on
  screen. Verified against the real source-derived vs pipeline-derived jump heights:
  **663 paired trials**, tight along the identity line, with a visible proportional bias in
  the difference view.
- Cross-dataset never pairs. An ambiguous key is dropped rather than paired arbitrarily.
- The difference view is refused when units differ, with an explanation.
- "interchangeability not established" stays on the surface.

### Methods / Provenance (audit F)

- Metric discovery from the registered vocabulary by readable name, id or dataset.
- Definition, class semantics, algorithm, version and a readable parameter summary populate
  immediately.
- Served results listed by readable scope, so a lineage opens by recognising an observation
  rather than typing a `dm-…` id.
- Full chain verified: dataset → silver artifact → canonical stream → algorithm → metric
  definition → processing run → derived metric → Gold row.
- Hashes and code revisions in collapsed technical-evidence sections.

### Quality / Runs / Inspector (audit K)

- Quality answers both questions from one screen: recorded quality state, and a rights matrix
  with attribution, commercial use, share-alike and redistribution as explicit terms. Every
  cell carries a shape as well as a colour.
- The empty issue list states what the absence means and does not mean.
- Runs communicates reproducibility: processor name first, status with a shape, unknown code
  revision flagged. Selecting a run opens code revision, parameters hash, window, outputs and
  every input checksum.
- The inspector pins the selected value's identity, value, scope and measurement class above
  the evidence tabs.

### Report Light

Verified at 1600×1000: full parity, readable contrast, semantic colours preserved.

---

## 4. Performance

The control plane shipped with primary keys and uniqueness constraints only — **zero
foreign-key indexes**. Every serving query filtering on a non-leading column resolved by
sequential scan of the largest authority.

| Endpoint | Before | After | Factor |
|---|---:|---:|---:|
| `GET /api/runs?limit=200` | **69.08 s** | **0.047 s** | 1470× |
| `GET /api/catalog/datasets` | 2.71 s | 0.036 s | 75× |
| `GET /api/metrics/definitions` | 0.49 s | 0.017 s | 29× |
| `GET /api/…/sessions/1925299` | — | 0.022 s | — |

`/api/runs` computed a per-run metric count with a correlated subquery over `derived_metric`
(~77k rows), 200 times per page.

Migrations `0005_serving_read_indexes` (12 read-path indexes) and `0006_metric_catalog_index`
(widen the metric index to `(metric_id, dataset_id)` for index-only catalog discovery).

**No denormalisation.** No column, constraint, uniqueness rule or measurement semantic
changed. Tables whose primary key already leads with the filtered column were left untouched.

---

## 5. Gate status

| Gate | State |
|---|---|
| TypeScript typecheck | **Pass** |
| ESLint | **Pass** — 0 errors, 2 hook-dependency warnings |
| Vitest | **Pass** — 141 tests, 20 files |
| Python serving + migrations + schema | **Pass** — 35 tests |
| ruff check / format | **Pass** |
| pyright (serving) | **Pass** — 0 errors |
| API client/schema generation | Regenerated and committed |
| Playwright acceptance / responsive / smoke / lazy-loading / visual / theme | **Pass — 49 tests** |
| axe accessibility | **Pass — 8 routes, no serious or critical violations** |
| Production build | **Pass** — intentional lazy ECharts/Pose chunks remain split |
| API schema drift | **Pass** — generated schema is in sync |
| Browser console | **Pass** — no page errors or console errors on smoke and screenshot routes; Three emits one known upstream deprecation warning |
| Deterministic screenshots | **Captured — 9 files at 1600×1000** |

---

## 6. Acceptance evidence

The final gates are recorded in the table above. The nine required fixed-viewport captures are
listed in [SCREENSHOTS.md](./SCREENSHOTS.md). They are evidence of presentation and renderer
reachability, not scientific validation; the scientific contract remains the served API,
provenance and processor test suite.

---

## 7. Contracts preserved

Checked and unchanged throughout:

- URL owns durable analytical context; TanStack Query owns server state; Zustand owns
  transient playback state. No duplication across layers.
- Playback never writes the URL.
- ECharts remains the only general chart engine. No second stack introduced.
- Heavy renderers stay lazy.
- Dataset/session stream capability is gated by registered canonical artifacts; current-window
  availability is evaluated separately from the columns actually populated in that window.
- Measurement class, quality and rights use shape and text as well as colour.
- Pose display uses the explicit rigid right-handed rotation `R_x(+90°): [x,y,z] → [x,z,−y]`
  and states that it is display-only, with no absolute-height interpretation.
- Compare withholds classical ±1.96 SD agreement limits when its descriptive difference-vs-mean
  screen detects proportional/magnitude-dependent bias; an appropriate model is required before
  agreement interpretation.
- No fabricated metric, pairing, anatomy or coordinate claim. Every chart plots served Gold
  rows; descriptive summaries are labelled as descriptions of the values in view, never as
  pipeline results.
- Locked scientific language preserved: "source-derived reference", "model-estimated",
  "provider p90 predicted error radius", "interchangeability not established".
