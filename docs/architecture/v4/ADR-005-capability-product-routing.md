# ADR-005: derive capability and route by grain

Status: accepted for V4.

Compute profiles deterministically from source catalog evidence, registered streams, materialized artifacts and accepted processor outputs. Preserve evidence origin and expose upstream and local readiness separately; model-estimated evidence stays explicit.

MatchLab, GameLab, SeasonLab and PerformanceLab routes consume local capabilities and grain requirements. Provider names do not select products. This freezes a routing contract without implementing the deferred product surfaces.
