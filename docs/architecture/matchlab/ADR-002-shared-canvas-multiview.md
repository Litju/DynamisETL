# ADR-002: One Canvas with Drei scissored views

Status: accepted for implementation.

## Decision

Use one R3F Canvas and one Three renderer for all MatchLab view modes. Use Drei View scissor rendering for Field-only, Pose-only, split, Tactical Map, Structure Lift and subject-focus views. Field uses orthographic Tactical Map by default; Structure Lift is oblique orthographic, while Pose retains its independent 3D camera. Each viewport owns its camera but shares scene resources, canonical time and player selection.

The viewport ratio and final product composition belong to RES-114. This ADR defines the rendering foundation and does not pre-implement that composition.

## Consequences

The Canvas remains stable while the MatchLab view mode changes. View sizing follows its DOM container. Camera state is presentation state and cannot alter data coordinates. Accessible DOM summaries remain outside Canvas.

