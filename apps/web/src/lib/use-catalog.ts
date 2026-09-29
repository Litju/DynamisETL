/**
 * Stage A metadata bootstrap, shared by Research, Data, entity context and
 * the command palette.
 *
 * Only lightweight navigation metadata: the semantic read model, dataset
 * summaries and sports contest summaries. No tracking, Pose, play-by-play or
 * metric tables are ever requested from here. The three queries are cached
 * for minutes so drilling through competitions, teams and players is
 * answered from memory.
 */

import { useQuery, type QueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import type { CatalogResourceView, DatasetSummary, SportsCatalogMatchView } from "@/api/types";
import {
  catalogReadModelQuery,
  datasetsQuery,
  servingStatusQuery,
  sportsCatalogMatchesQuery,
} from "@/lib/api/queries";
import {
  buildSportsTree,
  buildStudies,
  summarizeCatalog,
  type CatalogSummary,
  type SportNode,
  type StudyNode,
} from "@/lib/catalog-model";

export const METADATA_STALE_MS = 5 * 60_000;

export interface CatalogBootstrap {
  readonly resources: readonly CatalogResourceView[];
  readonly datasets: readonly DatasetSummary[];
  readonly matchesByContest: ReadonlyMap<string, SportsCatalogMatchView>;
  readonly tree: readonly SportNode[];
  readonly studies: readonly StudyNode[];
  readonly summary: CatalogSummary;
  readonly isPending: boolean;
  readonly isError: boolean;
  readonly error: unknown;
  readonly refetch: () => void;
}

const EMPTY_RESOURCES: readonly CatalogResourceView[] = [];
const EMPTY_DATASETS: readonly DatasetSummary[] = [];
const EMPTY_MATCHES: readonly SportsCatalogMatchView[] = [];

export function useCatalog(): CatalogBootstrap {
  const readModel = useQuery({ ...catalogReadModelQuery(), staleTime: METADATA_STALE_MS });
  const datasets = useQuery({ ...datasetsQuery(), staleTime: METADATA_STALE_MS });
  const matches = useQuery({ ...sportsCatalogMatchesQuery(), staleTime: METADATA_STALE_MS });
  const resources = readModel.data?.resources ?? EMPTY_RESOURCES;
  const datasetList = datasets.data ?? EMPTY_DATASETS;
  const matchList = matches.data ?? EMPTY_MATCHES;
  const tree = useMemo(() => buildSportsTree(resources), [resources]);
  const studies = useMemo(() => buildStudies(datasetList, resources), [datasetList, resources]);
  const summary = useMemo(() => summarizeCatalog(resources), [resources]);
  const matchesByContest = useMemo(
    () => new Map(matchList.map((match) => [match.contest_id, match])),
    [matchList],
  );
  return {
    resources,
    datasets: datasetList,
    matchesByContest,
    tree,
    studies,
    summary,
    isPending: readModel.isPending || datasets.isPending,
    isError: readModel.isError || datasets.isError,
    error: readModel.error ?? datasets.error,
    refetch: () => {
      void readModel.refetch();
      void datasets.refetch();
      void matches.refetch();
    },
  };
}

/** Warm the Stage A metadata once at application start (never dense data). */
export function prefetchBootstrap(client: QueryClient): void {
  void client.prefetchQuery({ ...catalogReadModelQuery(), staleTime: METADATA_STALE_MS });
  void client.prefetchQuery({ ...datasetsQuery(), staleTime: METADATA_STALE_MS });
  void client.prefetchQuery({ ...sportsCatalogMatchesQuery(), staleTime: METADATA_STALE_MS });
  void client.prefetchQuery(servingStatusQuery());
}
