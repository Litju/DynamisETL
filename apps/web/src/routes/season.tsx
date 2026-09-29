import { createRoute, type AnyRoute, useSearch } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { LoadingPanel } from "@/components/common/StatePanel";
import { parseSearch, seasonSearchSchema } from "@/lib/search";
import { usePublishSeasonContext } from "@/lib/use-world-context";

const SeasonLab = lazy(() =>
  import("@/components/season/SeasonLab").then((module) => ({ default: module.SeasonLab })),
);

/** SeasonLab route: the workbench chunk (and ECharts) load only when opened. */
export function defineSeasonRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/season",
    validateSearch: (search: Record<string, unknown>) => parseSearch(seasonSearchSchema, search),
    component: SeasonPage,
  });
}

function SeasonPage() {
  usePublishSeasonContext(useSearch({ from: "/season" }));
  return (
    <Suspense fallback={<LoadingPanel label="Opening Season World" />}>
      <SeasonLab />
    </Suspense>
  );
}
