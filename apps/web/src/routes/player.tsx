import { createRoute, lazyRouteComponent, type AnyRoute } from "@tanstack/react-router";

import { entitySearchSchema, parseSearch } from "@/lib/search";

/** Player entity context: the cross-World bridge. */
export function definePlayerRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/data/player/$subjectId",
    validateSearch: (search: Record<string, unknown>) => parseSearch(entitySearchSchema, search),
    component: lazyRouteComponent(() => import("@/pages/player"), "PlayerPage"),
  });
}
