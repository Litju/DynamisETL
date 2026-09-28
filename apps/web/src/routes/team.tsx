import { createRoute, lazyRouteComponent, type AnyRoute } from "@tanstack/react-router";

import { entitySearchSchema, parseSearch } from "@/lib/search";

/** Team entity context. */
export function defineTeamRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/data/team/$teamId",
    validateSearch: (search: Record<string, unknown>) => parseSearch(entitySearchSchema, search),
    component: lazyRouteComponent(() => import("@/pages/team"), "TeamPage"),
  });
}
