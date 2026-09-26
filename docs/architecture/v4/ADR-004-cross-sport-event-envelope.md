# ADR-004: portable event envelope with source semantics retained

Status: accepted for V4.

Store contest/period, sequence, source event ID, provider namespace/type, optional canonical monotonic time, source-clock JSON, optional team/subject/location, and versioned provider/sport attributes. Source event type is always retained. Location requires a declared spatial authority.

This envelope supports shared event storage without a universal sport-specific mega-table. Canonical event-family normalization remains optional and versioned. Kloppy may inform football adapters but is not the cross-sport schema authority.
