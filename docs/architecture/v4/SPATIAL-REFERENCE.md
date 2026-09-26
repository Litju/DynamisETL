# Spatial reference and surface geometry

`SpatialReference` declares units, axes, origin, handedness and the source coordinate authority. `SurfaceGeometry` declares a versioned named surface, its dimensions and canonical display transform. Keep the source transform and provider coordinates recoverable; transformations are explicit and never implied by rendering.

The model represents football pitches, basketball courts, hockey rinks and other declared surfaces without forcing a 105×68 m frame. Direction changes can be period-scoped where the source declares them. Unknown dimensions remain unknown; coordinate extents are not a geometry source. Existing `CoordinateFrame` and `FrameTransform` records remain valid and authoritative for the existing scientific streams.
