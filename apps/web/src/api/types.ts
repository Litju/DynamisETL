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
export type SourceCapabilityView = components["schemas"]["SourceCapabilityView"];
export type SportsCatalogMatchView = components["schemas"]["SportsCatalogMatchView"];
export type StreamView = components["schemas"]["StreamView"];
export type MetricValue = components["schemas"]["MetricValue"];
export type MetricPage = components["schemas"]["MetricPage"];
export type MetricMethodology = components["schemas"]["MetricMethodology"];
export type PoseRangeReportView = components["schemas"]["PoseRangeReportView"];
export type ProvenanceGraph = components["schemas"]["ProvenanceGraph"];
export type QualityIssuePage = components["schemas"]["QualityIssuePage"];
export type QualityIssueView = components["schemas"]["QualityIssueView"];
export type RunPage = components["schemas"]["RunPage"];
export type RightsPage = components["schemas"]["RightsPage"];
export type DenseWindow = components["schemas"]["DenseWindow"];
export type DenseWindowMeta = components["schemas"]["DenseWindowMeta"];
export type ArtifactRef = components["schemas"]["ArtifactRefView"];
export type ArtifactDetail = components["schemas"]["ArtifactDetail"];
export type MetricCatalogEntry = components["schemas"]["MetricCatalogEntry"];
export type TrialView = components["schemas"]["TrialView"];
export type SessionParticipantView = components["schemas"]["SessionParticipantView"];
export type TacticalCapabilityView = components["schemas"]["TacticalCapabilityView"];
export type TacticalQualityView = components["schemas"]["TacticalQualityView"];
export type TacticalMethodologyPage = components["schemas"]["TacticalMethodologyPage"];
export type TacticalSeriesView = components["schemas"]["TacticalSeriesView"];
export type TacticalEventPage = components["schemas"]["TacticalEventPage"];
export type SeasonEditionView = components["schemas"]["SeasonEditionView"];
export type SeasonFamilyRef = components["schemas"]["SeasonFamilyRef"];
export type SeasonFamilyView = components["schemas"]["SeasonFamilyView"];
export type SeasonMetricView = components["schemas"]["SeasonMetricView"];
export type SeasonRowView = components["schemas"]["SeasonRowView"];
export type SeasonRowPage = components["schemas"]["SeasonRowPage"];
export type SeasonProfileView = components["schemas"]["SeasonProfileView"];
export type SeasonRankedMetricView = components["schemas"]["SeasonRankedMetricView"];
export type SeasonPopulationView = components["schemas"]["SeasonPopulationView"];
export type SeasonPlayerLinksView = components["schemas"]["SeasonPlayerLinksView"];
export type GameEditionView = components["schemas"]["GameEditionView"];
export type GameFamilyRef = components["schemas"]["GameFamilyRef"];
export type GameSummaryView = components["schemas"]["GameSummaryView"];
export type GamePage = components["schemas"]["GamePage"];
export type GameDetailView = components["schemas"]["GameDetailView"];
export type GamePeriodView = components["schemas"]["GamePeriodView"];
export type GamePlayView = components["schemas"]["GamePlayView"];
export type GamePlayPage = components["schemas"]["GamePlayPage"];
export type GameBoxView = components["schemas"]["GameBoxView"];
export type GameBoxFamilyView = components["schemas"]["GameBoxFamilyView"];
