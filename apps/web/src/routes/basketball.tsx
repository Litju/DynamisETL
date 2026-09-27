import { createRoute, type AnyRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { LoadingPanel } from "@/components/common/StatePanel";
import { parseSearch, basketballSpatialSearchSchema } from "@/lib/search";

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
    component: () => (
      <Suspense fallback={<LoadingPanel label="Opening basketball spatial game" />}>
        <BasketballSpatialGame />
      </Suspense>
    ),
  });
}
