import {
  createRouter,
  parseSearchWith,
  stringifySearchWith,
  type RouterHistory,
} from "@tanstack/react-router";

import { defineBasketballRoute } from "@/routes/basketball";
import { defineCompareRoute } from "@/routes/compare";
import { defineCatalogRedirectRoute, defineDataRoute } from "@/routes/data";
import { defineEditionRoute } from "@/routes/edition";
import { defineGamesRoute } from "@/routes/games";
import { defineLabRoute } from "@/routes/lab";
import { defineLabIndexRoute } from "@/routes/lab-index";
import { defineLibraryRoute } from "@/routes/library";
import { defineMethodsRoute } from "@/routes/methods";
import { definePerformanceRoute } from "@/routes/performance";
import { definePlayerRoute } from "@/routes/player";
import { defineQualityRoute } from "@/routes/quality";
import { defineResearchRoute } from "@/routes/research";
import { defineRootRoute } from "@/routes/root";
import { defineRunsRoute } from "@/routes/runs";
import { defineSeasonRoute } from "@/routes/season";
import { defineTeamRoute } from "@/routes/team";

/**
 * Assemble a fresh route tree for one router instance.
 *
 * Information architecture (RES-129): Research (`/`), Data (`/data`, entity
 * context under `/data/...`), Library (`/library`, `/methods`, `/runs`,
 * `/quality`) and the four Worlds (`/lab`, `/games`, `/season`,
 * `/performance`, plus the basketball court at `/basketball`).
 *
 * TanStack Router route instances are owned by a single router, and tests build
 * memory routers per case, so the tree is created through factories.
 */
export function buildRouteTree() {
  const root = defineRootRoute();
  return root.addChildren([
    defineResearchRoute(root),
    defineDataRoute(root),
    defineCatalogRedirectRoute(root),
    defineEditionRoute(root),
    defineTeamRoute(root),
    definePlayerRoute(root),
    definePerformanceRoute(root),
    defineLabIndexRoute(root),
    defineLabRoute(root),
    defineCompareRoute(root),
    defineGamesRoute(root),
    defineBasketballRoute(root),
    defineSeasonRoute(root),
    defineLibraryRoute(root),
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
