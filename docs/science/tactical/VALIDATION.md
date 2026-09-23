# Tactical validation plan

The tests in `tests/test_tactical_geometry.py`, `tests/test_tactical_territory.py`, `tests/test_tactical_influence.py`, and `tests/test_tactical_events.py` are the CI known-answer gate. The real-data receipts are local, external-data evidence and never contain raw rows.

## Level A known answers

- Four symmetric points around the origin: centroid `(0,0)`, length `2 m`, width `2 m`, hull area `4 m²`, pairwise mean `2 + sqrt(2) / 2` m.
- A two-player line: nearest and pairwise distances equal the analytic separation; width is zero and length:width is unavailable.
- Collocated points: stable identity order is deterministic and no NaN is emitted.
- Player dropout: valid-player count and quality evidence change; no imputed player is introduced.
- A side swap changes frame-axis x sign but does not change scalar distances or area. Attack-normalized output remains unavailable without a direction authority.
- Rates are exact finite differences in SI units and do not cross a stream boundary.

## Level B known answers

- Four points at the corners of a 10 m × 10 m pitch produce four 25 m² cells and 100 m² total control.
- A symmetric two-player split produces equal areas and a 50/50 team split.
- A coincident pair produces one deterministic owner and one zero-area cell.
- A point outside the pitch is clamped only for territory, flagged, and the returned cells remain bounded by the pitch.
- Missing or single-player frames fail the declared minimum gate without a fake full-pitch cell.

## Level C known answers

- Zero velocity is distance/speed plus reaction time.
- Equal-distance defenders tie by stable object id and produce bounded influence percentages.
- Increasing reaction time increases arrival time monotonically.
- Increasing distance never decreases arrival time under the frozen model.
- Influence percentages are within `[0,100]`; selected influence area is within `[0,pitch_area]`.
- Parameter changes produce different parameter hashes and a sensitivity receipt.

## Level D known answers

- An event and tracking sample on the same timestamp join exactly.
- A one-frame offset joins only when within the declared tolerance.
- An out-of-tolerance event remains unsynchronized instead of being invented into a snapshot.
- Provider event type/subtype/player/team/context are preserved; the processor does not emit a fabricated `line_break`, `possession`, `pressure`, or phase label.

## Real-data acceptance

The DFL acceptance run must prove non-empty A/B/C series, source-event snapshot rows, full input checksums, code SHA, method/version, coordinate frame and quality diagnostics. SkillCorner acceptance must prove A/B and the partial C gate while retaining `MODEL_ESTIMATED`/extrapolation disclosure. Women’s/GNSS must prove the tactical capability response is unavailable and that no tactical processor is run. Real DFL receipts live under the configured external cache root.
