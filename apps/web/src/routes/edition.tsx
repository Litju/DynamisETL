import { createRoute, lazyRouteComponent, type AnyRoute } from "@tanstack/react-router";

import { editionSearchSchema, parseSearch } from "@/lib/search";

/** Competition/Season entity context. */
export function defineEditionRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/data/edition/$editionId",
    validateSearch: (search: Record<string, unknown>) => parseSearch(editionSearchSchema, search),
    component: lazyRouteComponent(() => import("@/pages/edition"), "EditionPage"),
  });
}
