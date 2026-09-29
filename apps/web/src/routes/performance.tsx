import { createRoute, lazyRouteComponent, type AnyRoute } from "@tanstack/react-router";

import { parseSearch, performanceSearchSchema } from "@/lib/search";

/** Performance World entry: Study -> Session -> Trial -> Subject. */
export function definePerformanceRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/performance",
    validateSearch: (search: Record<string, unknown>) => parseSearch(performanceSearchSchema, search),
    component: lazyRouteComponent(() => import("@/pages/performance"), "PerformanceEntry"),
  });
}
