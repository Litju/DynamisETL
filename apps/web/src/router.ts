import {
  createRouter,
  parseSearchWith,
  stringifySearchWith,
  type RouterHistory,
} from "@tanstack/react-router";

import { defineCatalogRoute } from "@/routes/catalog";
import { defineCompareRoute } from "@/routes/compare";
import { defineLabRoute } from "@/routes/lab";
import { defineLabIndexRoute } from "@/routes/lab-index";
import { defineMethodsRoute } from "@/routes/methods";
import { defineQualityRoute } from "@/routes/quality";
import { defineRootRoute } from "@/routes/root";
import { defineRunsRoute } from "@/routes/runs";

/**
 * Assemble a fresh route tree for one router instance.
 *
 * TanStack Router route instances are owned by a single router, and tests build
 * memory routers per case, so the tree is created through factories.
 */
export function buildRouteTree() {
  const root = defineRootRoute();
  return root.addChildren([
    defineCatalogRoute(root),
    defineLabIndexRoute(root),
    defineLabRoute(root),
    defineCompareRoute(root),
    defineMethodsRoute(root),
    defineRunsRoute(root),
    defineQualityRoute(root),
  ]);
}

/** Build a router with the product search-parameter serialization contract. */
export function createAppRouter(history?: RouterHistory) {
  return createRouter({
    routeTree: buildRouteTree(),
    ...(history ? { history } : {}),
    defaultPreload: "intent",
    defaultPreloadStaleTime: 30_000,
    scrollRestoration: false,
    // Durable analytical search parameters are flat typed strings; the default
    // JSON coercion would turn a decimal-nanosecond `t_ns` or a numeric subject
    // id into a number before validation.
    parseSearch: parseSearchWith((value) => value),
    stringifySearch: stringifySearchWith(String),
  });
}

export const router = createAppRouter();

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
