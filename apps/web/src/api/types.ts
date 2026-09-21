/**
 * Convenience aliases over the generated OpenAPI schema.
 *
 * The generated `schema.d.ts` remains the single DTO authority; this module only
 * names the shapes the UI references most often.
 */

import type { components } from "@/api/schema";

export type DatasetSummary = components["schemas"]["DatasetSummary"];
export type DatasetDetail = components["schemas"]["DatasetDetail"];
export type SessionSummary = components["schemas"]["SessionSummary"];
export type SessionDetail = components["schemas"]["SessionDetail"];
export type StreamView = components["schemas"]["StreamView"];
export type MetricValue = components["schemas"]["MetricValue"];
export type MetricPage = components["schemas"]["MetricPage"];
export type MetricMethodology = components["schemas"]["MetricMethodology"];
export type ProvenanceGraph = components["schemas"]["ProvenanceGraph"];
export type QualityIssuePage = components["schemas"]["QualityIssuePage"];
export type RunPage = components["schemas"]["RunPage"];
export type RightsPage = components["schemas"]["RightsPage"];
export type DenseWindow = components["schemas"]["DenseWindow"];
export type DenseWindowMeta = components["schemas"]["DenseWindowMeta"];
export type ArtifactRef = components["schemas"]["ArtifactRefView"];
export type ArtifactDetail = components["schemas"]["ArtifactDetail"];
export type MetricCatalogEntry = components["schemas"]["MetricCatalogEntry"];
export type TrialView = components["schemas"]["TrialView"];
export type SessionParticipantView = components["schemas"]["SessionParticipantView"];
