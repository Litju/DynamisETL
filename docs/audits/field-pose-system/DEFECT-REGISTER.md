# RES-112 defect register — Field, Pose and workbench

Audit authority: the running workbench (`apps/web` Vite dev server) against the real local
analytical API (`uv run dynamis-serve`) and the accepted local corpus, inspected before any
repair on branch `codex/res-110-tactical-intelligence` at `5a6203c`.

- Real contexts: DFL/Sportec IDSSE `DFL-MAT-J03WPY` (25 Hz tracking, 1,444 source events);
  SkillCorner Open Data `1925299` (10 Hz tracking, 25 Hz body pose, 23 pose subjects).
- Evidence harness: `apps/web/e2e-real/audit-capture.spec.ts` (no mocks, no route interception),
  `RES112_AUDIT_PHASE=before`. Screenshots and the console/API log are under
  [`output/playwright/res-112/before/`](../../../output/playwright/res-112/before/).
- Viewports: 1440×900 (primary), 1600×1000 and 1366×768.
- Control-plane inspection: `dynamis.processing_run` / `dynamis.derived_metric` in the local
  PostgreSQL 18.6 instance.

Severity: **S1** blocks a flagship path or corrupts scientific meaning · **S2** wrong or
misleading analytical state · **S3** degraded usability/readability · **S4** polish.

Classes: functional · state/query · data/materialization · rendering · scientific-semantics ·
accessibility · performance · UX/UI · false positive.

## Index

| id | surface | class | severity | title | status |
| --- | --- | --- | --- | --- | --- |
| [D-01](#d-01) | Field / data | data/materialization | S1 | DFL tactical Level A/B/C/D never materialized; every tactical tab is empty | open |
| [D-02](#d-02) | Field / data | data/materialization | S2 | Level C influence never materialized for any dataset although capability declares it | open |
| [D-03](#d-03) | Overview / data | scientific-semantics | S1 | Ball trajectory served as athlete locomotor metrics and headlined as top performer | open |
| [D-04](#d-04) | Runbook | data/materialization | S2 | No deterministic preparation path; flagship routes open silently empty | open |
| [F-01](#f-01) | Field + Pose | state/query | S1 | Laboratory opens with no canonical time: playhead unavailable, frame −1, renderers disagree | open |
| [F-02](#f-02) | Field / transport | functional | S1 | DFL playback cannot start: first advance is declared "end of artifact" | open |
| [F-03](#f-03) | Field / Pixi | performance | S1 | Pixi renderer destroyed and rebuilt on every playback frame when tactical data exists | open |
| [F-04](#f-04) | Field / Pixi | rendering + scientific-semantics | S1 | Tactical overlays are not the current canonical frame | open |
| [F-05](#f-05) | Field / Pixi | rendering | S2 | Overlay team colours hard-coded to a DFL group-id suffix; hulls contradict player colours | open |
| [F-06](#f-06) | Field / state | state/query | S2 | Pitch entity selection writes the Pose `subject` key with a history push per click | open |
| [F-07](#f-07) | Field / Pixi | UX/UI | S3 | Overlay layer order/weights: hull stroke dominates, ball and selection can be occluded | open |
| [T-01](#t-01) | Tactical pane | UX/UI + data | S1 | Generic "NO DATA" hides the real reason (missing materialization vs unsupported vs no rows) | open |
| [T-02](#t-02) | Tactical pane | performance + state/query | S1 | Live tab query key moves every animation frame during playback | open |
| [T-03](#t-03) | Tactical pane | scientific-semantics | S2 | Live tab shows one arbitrary team row; no per-team context | open |
| [T-04](#t-04) | Tactical pane | scientific-semantics | S2 | Space tab shows the first row of the window, not the current frame, one team only | open |
| [T-05](#t-05) | Tactical pane | scientific-semantics | S2 | Range tab interleaves both teams into one series and silently uses a ±1 s window | open |
| [T-06](#t-06) | Tactical pane | functional | S2 | Events tab reports "no source events" when the snapshot artifact is missing | open |
| [T-07](#t-07) | Tactical pane | scientific-semantics | S2 | Evidence strip asserts `PIPELINE_DERIVED` for absent data | open |
| [T-08](#t-08) | Tactical pane | UX/UI | S3 | Report JSON carries no artifact/run identity; tabs wrap at 1366 px | open |
| [P-01](#p-01) | Pose | state/query | S2 | Pose opens with playhead unavailable (shared root with F-01) | open |
| [P-02](#p-02) | Pose / 3D | rendering | S2 | Landmark glyphs black on the dark scene; skeleton hard to read; error radii read as artefacts | open |
| [P-03](#p-03) | Pose / state | state/query + UX | S2 | Render mode, coordinate authority and camera ownership are three conflicting states | open |
| [P-04](#p-04) | Pose / 3D | rendering | S3 | All-subject world: identical colours, tiny figures, selected subject not distinguished | open |
| [P-05](#p-05) | Pose / state | UX/UI | S3 | Subject switch while playing silently stops playback | open |
| [P-06](#p-06) | Pose / controls | UX/UI + a11y | S3 | Layer controls are native checkboxes outside the instrument language | open |
| [S-01](#s-01) | Transport | functional | S1 | No timeline: Field/Pose cannot seek to an arbitrary time | open |
| [S-02](#s-02) | Lab route | state/query | S3 | A deep link to a view the session cannot open leaves no tab selected | open |
| [S-03](#s-03) | Overview | rendering | S3 | Bar value labels overlap; metric table clips entity/class; KPI value wraps | open |
| [S-04](#s-04) | Shell | UX/UI | S4 | Breadcrumb truncates route and trial names at 1440 px | open |
| [S-05](#s-05) | Catalog | scientific-semantics | S3 | Catalog advertises an Events laboratory for SkillCorner, which has no accepted event artifact | open |
| [S-06](#s-06) | Runs | UX/UI + scientific-semantics | S3 | Tactical runs read "0 metrics"; processor chart formats counts as `950.0` / `0.000` | open |
| [S-07](#s-07) | API + shell | state/query + UX/UI | S3 | Registered team and player labels are never served; every surface shows raw provider ids | open |
| [FP-01](#fp-01) | Catalog | false positive | — | Dataset name mojibake | closed (not a defect) |
| [FP-02](#fp-02) | Console | false positive | — | `THREE.Clock` deprecation and GL `ReadPixels` stall warnings | closed (upstream / headless capture) |

---

## Data and materialization

### D-01

- **Surface:** Field tactical pane and overlays, DFL.
- **Steps:** open `/lab/dfl-sportec-idsse/DFL-MAT-J03WPY?view=field`; click every tactical tab.
- **Expected:** capability declares A `supported`, B `supported`, C `supported_partial`,
  D `supported_source_snapshots_only`; Live/Space/Range/Events/Report show real processor output.
- **Actual:** `GET /api/tactical/artifacts?dataset_id=dfl-sportec-idsse` returns `[]`;
  `processing_run` has no `tactical.*` run for DFL. All tabs render "NO DATA"; no Hull/Territory
  toggles exist on the DFL pitch.
- **Root cause:** the tactical Dagster assets (`dfl_tactical_*_processing`) were registered but
  never materialized locally; nothing verifies that a supported capability has artifacts.
- **Severity:** S1. **Scientific impact:** a declared-supported capability silently yields nothing.
  **UX impact:** the flagship DFL tactical laboratory is empty.
- **Before:** `before/04-field-dfl-live.png`, `05-field-dfl-{space,range,events,report}.png`.
- **Fix commit:** — · **Verification:** —

### D-02

- **Surface:** Field Space tab and Influence layer, DFL and SkillCorner.
- **Steps:** list tactical artifacts for SkillCorner.
- **Expected:** Level C (`tactical.arrival_time`) `team_influence`/`influence_grid` available where
  the capability declares `supported_partial(_with_model_input_quality)`.
- **Actual:** only `tactical.team_geometry` and `tactical.spatial_territory` runs exist for
  SkillCorner (2 each); no Level C run anywhere. The Influence toggle is simply absent, with no
  explanation.
- **Root cause:** same as D-01 — no preparation path materializes Level C.
- **Severity:** S2. **Scientific impact:** the model-estimated surface cannot be compared with the
  deterministic territory. **UX impact:** silent capability gap.
- **Before:** `before/07-field-sc-default.png` (no Influence toggle).
- **Fix commit:** — · **Verification:** —

### D-03

- **Surface:** Overview headline, derived-metric table, Compare, Methods (DFL and SkillCorner).
- **Steps:** open DFL Overview; read "Highest total locomotor distance".
- **Expected:** locomotor (athlete) metrics only for athletes.
- **Actual:** the headline is `DFL-OBJ-0000XT · 14,454.5 m`. The tracking artifact types
  `DFL-OBJ-0000XT` as `object_type = ball`. The control plane serves
  `locomotor.distance_total = 14454.51 m`, `mean_speed 5.23 m/s`,
  `max_acceleration 286.09 m/s²` for the ball as athlete locomotor metrics.
- **Root cause:** `processors/locomotor.py::_entities` groups every `object_id` regardless of
  `object_type`, so the ball becomes a locomotor entity.
- **Severity:** S1. **Scientific impact:** a non-human trajectory is presented as the top athlete
  locomotor load; any cross-player comparison is contaminated.
  **UX impact:** the first number the reader sees is wrong.
- **Before:** `before/02-overview-dfl.png`.
- **Fix commit:** — · **Verification:** —

### D-04

- **Surface:** developer/demo startup.
- **Expected:** a single deterministic path verifies accepted local sources, materializes supported
  processors, verifies serving registration and prints flagship URLs, failing loudly otherwise.
- **Actual:** none exists; the only way to find D-01/D-02 was to open the product.
- **Root cause:** missing preparation contract.
- **Severity:** S2. **Fix commit:** — · **Verification:** —

## Field playback and state

### F-01

- **Surface:** Field and Pose (shared lab state spine).
- **Steps:** open any Field or Pose URL without `t_ns` (the URL produced by every in-app link).
- **Expected:** the laboratory lands on the first canonical frame of the selected stream and every
  surface (transport, header, pitch, tactical pane) reports the same time.
- **Actual:** Transport `PLAYHEAD — unavailable`, `COMMITTED —`; DFL header "No frame at this time"
  and footer `frame -1` while 23 entities are drawn; SkillCorner footer `frame 0`,
  `00:00:00.000`; tactical Live "No tactical frame at the current time".
- **Root cause:** `resolveLabDefaults` never resolves a canonical time; each renderer then falls
  back differently (`entitiesAt` → first frame, `frameIndexAt(…, 0n)` → −1 before DFL's 1.02 s
  start, tactical pane → no query).
- **Severity:** S1. **Scientific impact:** surfaces disagree about which frame is shown.
  **UX impact:** the default route looks broken.
- **Before:** `before/04-field-dfl-live.png`, `07-field-sc-default.png`, `09-pose-default.png`.
- **Fix commit:** — · **Verification:** —

### F-02

- **Surface:** Field transport, DFL.
- **Steps:** open DFL Field; press Play; wait 4 s.
- **Expected:** playback advances at 25 Hz.
- **Actual:** playhead jumps to `1020000000 ns` and stops; `playing` is cleared immediately.
- **Root cause:** `usePlaybackClock` starts from `0n` when no time is committed; the coordinator
  clamps to `canonicalMinNs` (1.02 s) and `allowAdvance` treats *reaching either canonical edge*
  as "ended", even when moving forward away from the start.
- **Severity:** S1. **Fix commit:** — · **Verification:** —
- **Before:** `before/06-field-dfl-after-play.png`.

### F-03

- **Surface:** Field Pixi renderer (any dataset with a tactical artifact).
- **Steps:** SkillCorner Field; toggle Territory; press Play.
- **Expected:** one Pixi application for the window; per-frame updates are imperative.
- **Actual:** the browser stalls (Playwright `page.screenshot` timed out after 10 s during the
  audit). `tacticalOverlay` is memoized on the per-frame `tacticalTimeNs` React subscription and is
  a dependency of the renderer-creation effect, so every playback frame re-renders `PitchView`,
  destroys the Pixi application and creates a new WebGL context.
- **Root cause:** renderer lifecycle keyed on per-frame derived state (introduced in `5a6203c`).
- **Severity:** S1. **Fix commit:** — · **Verification:** —

### F-04

- **Surface:** Field overlays (hull, territory, influence).
- **Steps:** SkillCorner Field default route, Hull on.
- **Expected:** overlays draw exactly the canonical frame the entities show.
- **Actual:** hull vertices do not sit on the drawn players. With no committed time the overlay
  uses the *last* row of the 27.5 s window while entities show the first frame. With a time, the
  overlay window requests `max_points=2000` over the whole chunk; `player_territory`
  (22 cells × 275 frames) exceeds it, so the API applies display reduction and the "nearest" cell
  set is a partial set from other frames. The ≤1 Hz influence grid is chosen by nearest time
  (possibly a future grid) with no disclosure.
- **Root cause:** overlay rows fetched as a reduced chunk and matched by nearest time instead of an
  exact current-frame read.
- **Severity:** S1. **Scientific impact:** geometry from another instant is drawn as the current
  shape. **Before:** `before/07-field-sc-default.png`, `14-1366x768-field-sc.png`.
- **Fix commit:** — · **Verification:** —

### F-05

- **Surface:** Field overlays.
- **Actual:** `drawTactical` colours a group "home" only when its id is `home` or ends in `00000P`
  (a DFL id); every SkillCorner team is "away" orange, and on DFL the overlay colour is the inverse
  of the dot colour assigned by `assignGroups`.
- **Root cause:** a second, hard-coded team-colour rule instead of the entity group map.
- **Severity:** S2. **Before:** `before/07-field-sc-default.png`.
- **Fix commit:** — · **Verification:** —

### F-06

- **Surface:** Field selection → URL → Pose.
- **Actual:** clicking a pitch entity calls `context.selectSubject(objectId)` (history **push**),
  writing the tracking object id (including `ball`) into the Pose `subject` key; the declared
  `entity` search key is never used.
- **Root cause:** Field entity and Pose subject share one durable key.
- **Severity:** S2. **Fix commit:** — · **Verification:** —

### F-07

- **Surface:** Field overlays.
- **Actual:** hull stroke 2 px at α 0.9 in the away colour sits above territory and below entities
  but has the heaviest weight on the canvas; with Territory + Hull the pitch is dominated by
  overlay colour. Model-estimated influence and deterministic territory share one fill language.
- **Severity:** S3. **Fix commit:** — · **Verification:** —

## Tactical Analysis pane

### T-01

- **Steps:** DFL Field, any tab.
- **Actual:** "NO DATA — No tactical frame at the current time. Select an exact tracking time or
  load a tactical processor artifact." The system knows the capability is supported and that no
  artifact is registered, but says neither.
- **Severity:** S1. **Before:** `before/04-field-dfl-live.png`. **Fix commit:** — · **Verification:** —

### T-02

- **Actual:** Live bounds are `playhead ± 1 s` read from the per-frame playhead; the
  `tacticalSeriesQuery` key changes on every animation frame during playback.
- **Root cause:** live query window keyed on transient playhead instead of the loaded chunk.
- **Severity:** S1 (request storm, flicker). **Fix commit:** — · **Verification:** —

### T-03

- **Actual:** `nearestRow` searches both teams' rows and shows whichever row is nearest in time;
  "Group" prints the raw provider id.
- **Severity:** S2. **Fix commit:** — · **Verification:** —

### T-04

- **Actual:** Space shows `territoryRows[0]` — the first row of the window — for one team only;
  it does not follow the playhead.
- **Severity:** S2. **Fix commit:** — · **Verification:** —

### T-05

- **Actual:** Without a committed range the Range tab uses the ±1 s live window, and plots both
  teams' rows as one "length" and one "width" series (zig-zag between teams); x axis is raw
  "canonical ms".
- **Severity:** S2. **Fix commit:** — · **Verification:** —

### T-06

- **Actual:** DFL Events: "No source events in the selected range" while the pitch header reports
  "3 source events in window" — the snapshot artifact is missing (D-01), not the events.
- **Severity:** S2. **Before:** `before/05-field-dfl-events.png`. **Fix commit:** — · **Verification:** —

### T-07

- **Actual:** the evidence strip falls back to `PIPELINE_DERIVED` when no series is loaded, asserting
  a measurement class for data that does not exist.
- **Severity:** S2. **Fix commit:** — · **Verification:** —

### T-08

- **Actual:** Report JSON lists counts and capability only (no artifact ids, run ids, parameter
  hashes, time window); at 1366×768 the tab strip wraps "Report" onto a second line.
- **Severity:** S3. **Before:** `before/05-field-dfl-report.png`, `14-1366x768-field-sc.png`.
- **Fix commit:** — · **Verification:** —

## Pose

### P-01

- Same root as [F-01](#f-01): Pose renders frame 0 while the transport says the playhead is
  unavailable. **Severity:** S2. **Before:** `before/09-pose-default.png`.

### P-02

- **Actual:** landmark spheres render near-black on the dark scene; the skeleton reads as thin lines
  with dark dots; p90 error radii render as pink half-arcs that read as artefacts.
- **Severity:** S2. **Before:** `before/09-pose-default.png`, `09-pose-subject-switch.png`.
- **Fix commit:** — · **Verification:** —

### P-03

- **Actual:** `allSubjects`, `coordinateMode` and `cameraMode` are three independent `useState`s
  mutated from four control groups. Reachable contradictions: all-subjects + `follow-subject`
  camera ("camera follow is disabled" text shown while follow is pressed); the "render mode"
  control is a toggle whose label never changes and reads as a select value.
- **Severity:** S2. **Before:** `before/09-pose-default.png`, `09-pose-all-subjects.png`.
- **Fix commit:** — · **Verification:** —

### P-04

- **Actual:** all-subject world draws 12 identical grey skeletons ~20 px tall; the selected subject
  is not distinguishable. **Severity:** S3. **Before:** `before/09-pose-all-subjects.png`.

### P-05

- **Actual:** switching subject during playback stops playback with no indication.
  **Severity:** S3.

### P-06

- **Actual:** eight native checkboxes with system accent colour and wrapping labels.
  **Severity:** S3. **Before:** `before/09-pose-default.png`.

## Whole system

### S-01

- **Actual:** the footer "Transport and timeline" has no timeline. Field and Pose can only step
  frame-by-frame or play; seeking to an arbitrary time (issue §3 playback: "seek") is impossible.
- **Severity:** S1. **Fix commit:** — · **Verification:** —

### S-02

- **Actual:** `/lab/dfl-sportec-idsse/DFL-MAT-J03WPY?view=signals` (no signals-capable stream):
  no tab selected, body "No stream selected. Select a stream in the explorer…".
- **Severity:** S3. **Before:** `before/03-signals-dfl.png`.

### S-03

- **Actual:** Overview "Total locomotor distance" value labels overlap for 18 bars; derived-metric
  table truncates entity to `DFL-OB…` and clips the class badge; KPI `14454.5 m` wraps.
- **Severity:** S3. **Before:** `before/02-overview-dfl.png`.

### S-04

- **Actual:** breadcrumb shows `Laborat…`, `perio…` at 1440 px and `Subject…` at 1366 px.
- **Severity:** S4. **Before:** `before/07-field-sc-default.png`.

### S-05

- **Actual:** SkillCorner catalog row shows an "Events" laboratory chip; the capability matrix states
  "no accepted local event or phase artifact".
- **Severity:** S3. **Before:** `before/01-catalog.png`.

### S-06

- **Actual:** tactical processors emit series artifacts, not scalar metrics, so their runs show
  `0` in the Metrics column and `0.000` bars in "Metrics produced by processor"; integer counts
  render as `950.0`. A reader concludes the tactical runs produced nothing.
- **Severity:** S3. **Before:** `before/13-runs.png`.

### S-07

- **Actual:** `dynamis.subject` stores `cohort` (team name, e.g. `1. FC Nürnberg`) and `notes`
  (`shirt 16 (Christopher Schindler)`) for all 40 DFL and 36 SkillCorner subjects, but
  `SessionParticipantView` serves only `subject_id`, `role`, `group_label`. The pitch, tactical
  pane, Pose selector and Overview therefore show `DFL-CLU-00000P`, `DFL-OBJ-0028BZ`, `11897`.
- **Root cause:** serving contract omits registered descriptive fields.
- **Severity:** S3. **Before:** `before/04-field-dfl-live.png`, `09-pose-default.png`.

## False positives

### FP-01

`curl` output of `/api/catalog/datasets` showed `IDSSE â€"` in the Windows console. The page renders
`IDSSE — integrated…` correctly (`before/01-catalog.png`); the API emits valid UTF-8. Terminal code
page only.

### FP-02

`THREE.Clock` deprecation is emitted by the installed R3F dependency (already recorded in RES-108);
`GL Driver Message … GPU stall due to ReadPixels` is emitted by Chromium while Playwright captures a
WebGL canvas. Neither is an application console error; both are tracked in the acceptance matrix
console allow-list with this justification.
