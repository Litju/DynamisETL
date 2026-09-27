import { createRoute, type AnyRoute } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { LoadingPanel } from "@/components/common/StatePanel";
import { parseSearch, gameSearchSchema } from "@/lib/search";

const GameLab = lazy(() =>
  import("@/components/gamelab/GameLab").then((module) => ({ default: module.GameLab })),
);

export function defineGamesRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/games",
    validateSearch: (search: Record<string, unknown>) => parseSearch(gameSearchSchema, search),
    component: () => (
      <Suspense fallback={<LoadingPanel label="Opening GameLab" />}>
        <GameLab />
      </Suspense>
    ),
  });
}
