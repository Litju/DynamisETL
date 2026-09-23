# Tactical methods

## Coordinate and identity authority

The processor accepts a declared rectangular pitch (`length_m`, `width_m`) and a `coordinate_frame_id`. It does not swap axes, translate origins, or flip sides implicitly. DFL/Sportec and SkillCorner tracking use their declared pitch-centred X/Y metres. Women’s/GNSS is geodetic and is not accepted as a pitch plane.

The processor groups rows by `(stream_id, t_rel_ns)`, keeps only finite `x_m/y_m`, and uses `object_type in {player, goalkeeper}` for team geometry. `group_id` must be present for team outputs. The ball is kept as a separate object. All inputs, including provider extrapolated rows, stay attributable through the quality envelope.

## Deterministic geometry

Geometry is computed with NumPy-free scalar/vector operations where the bounded frame size makes the method clearer. Convex hull uses the monotone-chain cross-product algorithm. Pairwise metrics use unordered pairs. Rates use adjacent canonical times and are not computed across a stream boundary or non-positive time delta.

## Clipped Voronoi

Voronoi cells are built by clipping the pitch rectangle against each pairwise perpendicular-bisector half-plane. This keeps the pitch boundary in the computation and avoids an unbounded Voronoi representation. The stable object id tie rule handles coincident points. The output carries `degenerate_point_count`, `outside_pitch_count`, `missing_player_count`, and `cell_area_sum_m2` so a reviewer can see when the geometry is weak.

## Arrival/influence

Level C uses the frozen bounded grid and parameter set in [`LEVEL-C-CONTRACT.md`](LEVEL-C-CONTRACT.md). Provider velocity takes precedence; a position-derived first difference is used only inside the declared same-entity gap bound. Otherwise velocity is zero and the quality envelope says `velocity_fallback=zero`. The result is never called measured territory. Exact-frame influence summaries are retained while bounded grids are sampled at the declared interval without crossing gaps.

## Event snapshots

The DFL source event stream is source-derived and already carries provider event identity, type, subtype, team/player ids, source context, and the transformed event location. A snapshot join selects the nearest tracking timestamp within an explicit tolerance on the shared provider clock. A tie is resolved by the lower canonical sample index. An event outside the tolerance is retained as an unsynchronized source event with no tracking geometry; it is not dropped or force-matched.

## Quality and provenance

Quality is explicit for each series: input row counts, missing/extrapolated counts, outside-pitch counts, degenerate counts, synchronization match counts, and unavailable reason when a capability gate fails. Processor results use the existing `ProcessorSpec`/`ProcessorResult` contract. External series are written through the existing checksum-addressed Parquet runtime, and scalar/range summaries remain control-plane values.
