import { createRoute, type AnyRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { LoadingPanel } from "@/components/common/StatePanel";
import { parseSearch, seasonSearchSchema } from "@/lib/search";

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
  return (
    <Suspense fallback={<LoadingPanel label="Opening SeasonLab" />}>
      <SeasonLab />
    </Suspense>
  );
}
