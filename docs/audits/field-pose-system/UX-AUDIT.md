# RES-112 UX/UI audit — Dynamis Instrument workbench

Scope: the whole workbench as it runs against the real local API before repair
(`output/playwright/res-112/before/`). Functional/state defects live in
[`DEFECT-REGISTER.md`](DEFECT-REGISTER.md); this document records hierarchy, affordance,
density and readability findings and the refinement direction. The design language is preserved:
dark scientific workstation, compact density, mono for identifiers/values, measurement class
always carried by text + shape + colour.

## 1. Hierarchy

| id | finding | evidence | direction |
| --- | --- | --- | --- |
| UX-H1 | Human context is secondary to ids. Pitch labels, the Field "Group" value, the Pose subject selector and Overview axis labels all show provider ids (`DFL-CLU-00000P`, `DFL-OBJ-0028BZ`, `11897`). The session already knows team names/roles for DFL and SkillCorner participants. | `04-field-dfl-live`, `02-overview-dfl`, `09-pose-default` | Lead with the served human label (team name, player name/shirt when served), keep ids secondary and copyable. Never invent labels the API does not serve. |
| UX-H2 | Right panes read as debug sidebars: an uppercase "TACTICAL ANALYSIS" title, a tab row, then a measurement badge floating on its own line and a long disclaimer before any value. | `04-field-dfl-live` | Sticky context header (dataset · period · time · selected entity), tab strip, then the primary value block; evidence/method moves to a compact footer row. |
| UX-H3 | Primary analytical values are not visually primary: Live tab values are 12 px mono in key/value rows identical to metadata. | `07-field-sc-default` pane | Per-team comparison block with larger tabular numerals, unit suffix in muted weight, team colour swatch + text. |
| UX-H4 | Empty/loading/error hierarchy is flat: every state is "NO DATA" + sentence, regardless of cause. | T-01 | Distinct state vocabulary (see §4) with a reason, the authority that decided it, and the next action. |
| UX-H5 | Breadcrumb spends width on long dataset names and truncates the part that changes (period, subject). | `07-field-sc-default` (`perio…`) | Shorter crumbs: dataset short name, session label, period; full names in `title`. |

## 2. Right panes (Field / Pose)

- Tactical tabs are bordered pills that wrap at 1366 px and look like buttons, not tabs.
  Direction: underline tab strip consistent with the lab view tabs (single line, `role=tab`,
  arrow-key navigation).
- No sticky context: scrolling Report/Events loses which team/time the values describe.
- Units and measurement class are not next to values (Live shows `m`, `m²` inline but no class per
  metric family; Level C is `MODEL_ESTIMATED` and must be labelled at the value).
- Pose telemetry is dense and readable but lacks the observed/unavailable glyph per row and does
  not highlight the selected joint row; the header repeats the subject id twice.
- Pose control column mixes subject, render mode, coordinate authority, camera ownership, error
  radius and eight native checkboxes in one scroll; at 1366 px the viewport for the skeleton drops
  to ~520 px.

## 3. Controls

| control | issue | direction |
| --- | --- | --- |
| Layer toggles (Field) | 20 px high pills, pressed = accent border only; no hint of deterministic vs model class | 24 px height, pressed = filled surface + check glyph; model-estimated layers carry a `model` mark |
| Transport | no timeline; rate select native; "reverse" text button; playhead ns in 10 px | add timeline scrubber with canonical bounds and committed range; consistent 28 px controls |
| Pose checkboxes | native bright-blue checkboxes, label wrapping | instrument-style switch rows with focus ring |
| Focus rings | inconsistent; several buttons rely on browser default | shared `focus-visible` ring token on every control |
| Disabled | `opacity-40` only on transport; Pose body-local disabled state unexplained | disabled controls carry a `title` reason |

## 4. Empty / unavailable vocabulary

The system can distinguish these causes and must say which applies:

| state | meaning | example |
| --- | --- | --- |
| loading | request in flight for the current scope | tactical series fetching |
| no data at this time | the artifact exists; no row at the current canonical frame | player not tracked at t |
| unsupported capability | the source authority cannot support it | SkillCorner Level D, Level E everywhere |
| not materialized | supported by capability, no processor artifact registered | DFL tactical before preparation |
| API failure | request failed | 5xx/timeout with retry |
| rights restriction | licence forbids the view | non-commercial gating |
| filtered out | current filter/range excludes rows | range with no events |

## 5. Field visual language (tactical)

- Overlay order must be semantic: pitch → influence (model surface, lowest) → territory (geometry
  fill) → hull/axes (outline) → trails → events → entities → selection → labels.
- Deterministic geometry: thin solid outlines in the owning team colour. Model-estimated influence:
  low-alpha fill with a hatched/dotted edge language and an explicit "model" legend entry.
- Hull currently 2 px at α 0.9 — dominates. Target 1.25 px at α 0.7, territory fill α ≤ 0.10.
- Ball must render above all overlays with a dark halo; selection ring + crosshair always on top.
- Defaults: Hull on (deterministic, low clutter); Territory and Influence off.

## 6. Pose visual language

- Landmarks: light glyphs with dark outline so they read on the dark grid; selected joint larger
  with accent ring; unavailable landmarks never drawn.
- Provider skeleton lines brighter than view-only cues; analytical segments distinct hue;
  error radii as faint rings, off by default.
- All-subject world: selected subject in accent colour and full size, others muted; camera frames
  the observed group bounds.
- Grid/fog subordinate to the skeleton.

## 7. Density and responsiveness

- 1440×900 and 1600×1000: no horizontal document overflow (measured `scrollWidth == innerWidth`).
- 1366×768: tactical tabs wrap; Pose centre area cramped; breadcrumb truncation.
- Overview charts overlap labels at 18 bars.

## 8. Motion

Current motion is limited to tab indicator transitions. Direction: restrained transitions only for
tab/pane content swap, overlay enable/disable and camera ownership changes; all gated on
`prefers-reduced-motion`.

## 9. Accessibility baseline (manual, before repair)

- Pitch canvas exposes `role=img` with a static label; it does not summarize the current frame
  for assistive technology beyond the header text.
- Pose canvas has no live text alternative beyond telemetry.
- Tactical tabs use `role=tab` but no `aria-controls`/`tabpanel` and no arrow-key roving.
- Layer toggles use `aria-pressed` correctly.
- Axe results for real routes are recorded in [`ACCEPTANCE-MATRIX.md`](ACCEPTANCE-MATRIX.md).

## Refinement record

Each refinement lands as an atomic commit and is listed here with its before/after evidence.

| unit | commit | before | after |
| --- | --- | --- | --- |
| — | — | — | — |
