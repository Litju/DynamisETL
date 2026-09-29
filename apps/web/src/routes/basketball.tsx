import { createRoute, type AnyRoute, useSearch } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { LoadingPanel } from "@/components/common/StatePanel";
import { parseSearch, basketballSpatialSearchSchema } from "@/lib/search";
import { usePublishCourtContext } from "@/lib/use-world-context";

const BasketballSpatialGame = lazy(() =>
  import("@/components/basketball/BasketballSpatialGame").then((module) => ({
    default: module.BasketballSpatialGame,
  })),
);

export function defineBasketballRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/basketball",
    validateSearch: (search: Record<string, unknown>) =>
      parseSearch(basketballSpatialSearchSchema, search),
    component: CourtWorld,
  });
}

/** Match World for basketball tracking: the court workbench, lazily loaded. */
function CourtWorld() {
  usePublishCourtContext(useSearch({ from: "/basketball" }));
  return (
    <Suspense fallback={<LoadingPanel label="Opening the court" />}>
      <BasketballSpatialGame />
    </Suspense>
  );
}
