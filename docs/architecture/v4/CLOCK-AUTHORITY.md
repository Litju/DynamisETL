# Clock authority

Keep monotonic media/source time, canonical contest/session time, period identity, game clock, shot/possession clock and scheduled/actual UTC timestamps as distinct values. A source clock can count up or down; its display direction does not establish monotonicity.

Each adapter declares a versioned mapping with clock kind, direction, period origin, scale, offset, authority and evidence before mapping to canonical `t_rel_ns`. Preserve source clock fields alongside canonical time. A missing mapping means canonical time is unavailable, not guessed.

The explicit SkillCorner Basketball acceptance target is 25 fps wall time with period, countdown game clock and shot clock. This contract supports that shape but RES-119 adds no basketball tracking ingestion.
