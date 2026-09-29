import { createRoute, lazyRouteComponent, redirect, type AnyRoute } from "@tanstack/react-router";

import { dataSearchSchema, parseSearch } from "@/lib/search";

/** Data Browser: what data exists (metadata only). */
export function defineDataRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/data",
    validateSearch: (search: Record<string, unknown>) => parseSearch(dataSearchSchema, search),
    component: lazyRouteComponent(() => import("@/pages/data"), "DataBrowser"),
  });
}

/** Legacy `/catalog` links land on the Data Browser with equivalent facets. */
export function defineCatalogRedirectRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/catalog",
    beforeLoad: ({ search }) => {
      const input = search as Record<string, unknown>;
      const sport = typeof input.sport === "string" ? input.sport : undefined;
      throw redirect({
        to: "/data",
        search: sport === "__human__"
          ? { domain: "human" }
          : {
              ...(sport ? { domain: "sports", sport } : {}),
              ...(typeof input.q === "string" ? { q: input.q } : {}),
              ...(typeof input.provider === "string" ? { provider: input.provider } : {}),
            },
        replace: true,
      });
    },
  });
}
