# Level C arrival-time / influence contract

This contract is frozen before the Level C processor. It is a `MODEL_ESTIMATED` result and is never described as measured territory, ground truth, possession probability, or source pressure.

## Parameters

| Parameter | Default | Meaning |
| --- | ---: | --- |
| `reaction_time_s` | `0.25` | Modelled response delay. |
| `max_speed_m_s` | `7.0` | Maximum planar speed assumption. |
| `max_acceleration_m_s2` | `3.0` | Maximum planar acceleration assumption. |
| `grid_x` | `21` | Bounded pitch-control grid columns. |
| `grid_y` | `14` | Bounded pitch-control grid rows. |
| `grid_interval_ns` | `1_000_000_000` | Minimum canonical interval between stored influence grids. |
| `max_velocity_gap_s` | `0.25` | Maximum same-entity time gap for a position-derived velocity. |

Every parameter is part of the processor parameter hash. The grid is a display/serving surface, not a replacement for the exact tracking source.

## Velocity authority

Finite canonical `vx_m_s/vy_m_s` values take precedence. When they are absent, the processor derives a first difference from the previous finite position for the same entity and group only when the time gap is positive and no greater than `max_velocity_gap_s`. Otherwise velocity is `(0,0)` and quality carries `velocity_fallback=zero`. The processor never derives velocity across periods or a larger data gap.

## Arrival time

For player position `p`, planar velocity `v`, target grid point `q`, reaction time `r`, acceleration `a`, and speed cap `s`:

1. Project the player through the reaction interval: `p_r = p + clamp_speed(v, s) * r`.
2. Let `u = min(||v|| + a*r, s)` and `d = ||q - p_r||`.
3. Let `d_cap = (s² - u²) / (2*a)`.
4. If `d <= d_cap`, travel time is `(-u + sqrt(u² + 2*a*d)) / a`.
5. Otherwise travel time is `(s-u)/a + (d-d_cap)/s`.
6. Arrival time is `r + travel time`. Zero-acceleration and zero-distance branches are explicit deterministic limits.

This is an interpretable bounded kinematic estimate, not a learned model. It does not use event labels, possession, formation, or attacking direction.

## Influence semantics

The minimum arrival time over all players owns each grid cell. Ties use `(group_id, entity_id)` lexical order. Team influence percentage is owned-cell count divided by total grid-cell count. Selected-player influence area is owned-cell count multiplied by cell area. Opponent minimum arrival is evaluated at the selected player's current location; it is not pressure-on-ball. A pressure-on-ball metric remains unavailable unless a source-resolved ball-carrier identity is supplied.

The exact-frame summary is emitted for every canonical timestamp. The bounded grid is emitted at the first frame and then at most once per `grid_interval_ns`, without interpolation across gaps. Quality includes velocity source/fallback counts, input measurement class, provider extrapolation count, and grid sampling.
