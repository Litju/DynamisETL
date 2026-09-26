# Sports semantic overlay

The overlay in `system-v4.json` sits above the existing scientific core.

| Entity | Authority and relation |
| --- | --- |
| Sport | Stable internal code and display name. |
| Competition | A league or tournament identity independent of an edition. |
| CompetitionEdition | A league season, finite tournament or other declared edition. |
| Team | Canonical identity; provider team IDs are aliases, never primary identity. |
| Contest | Generic game/match linked to a sport and to an edition when source authority identifies it. Scheduled/actual start, venue and home/away facts stay nullable when unknown. |
| ContestTeam | Team participation with source-declared side/order and authoritative score. |
| ContestPeriod | Source segment with source numbering and optional friendly label. Sport adapters define set/inning semantics. |
| TeamRosterMembership | Existing Subject linked to a team and edition over a validity interval. It creates no second athlete identity. |
| SessionSportContext | Explicit bridge from a scientific Session to a known Contest. |

An unclassified contest or session stays representable without inventing a league, season, team or period. Sport context can be known before contest context. Generic laboratory sessions remain valid with no sports rows.

Provider crosswalk keys include namespace, entity kind and provider ID, with validity interval, authority and metadata. Equal names alone never merge identities. Cross-provider consolidation requires explicit deterministic mapping evidence.
