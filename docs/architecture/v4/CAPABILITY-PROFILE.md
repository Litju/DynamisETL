# Capability profile

`CapabilityProfile` is computed from source catalog declarations, registered streams, materialized artifacts and accepted processors. Each evidence item names its capability, scope (upstream or local), origin and source record. Stable sorting and deduplication make the result deterministic.

The vocabulary is TRACKING, BALL_TRACKING, POSE, EVENTS, PHASES, PLAY_BY_PLAY, BOX_SCORE, LINEUP, LOCOMOTOR, TACTICAL, SEASON_AGGREGATE, FORCE, IMU, LPT and GNSS. `MODEL_ESTIMATED` is an evidence origin and remains distinguishable from source observations. A provider name is provenance only; it never becomes a capability or product selector.

Upstream availability never satisfies a local product route. A capability becomes locally available only through registered/materialized evidence or an accepted processor output. Missing and unsupported capabilities remain absent rather than inferred from a dataset label.
