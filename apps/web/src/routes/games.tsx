import { createRoute, type AnyRoute, useSearch } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { LoadingPanel } from "@/components/common/StatePanel";
import { parseSearch, gameSearchSchema } from "@/lib/search";
import { usePublishGameContext } from "@/lib/use-world-context";

const GameLab = lazy(() =>
  import("@/components/gamelab/GameLab").then((module) => ({ default: module.GameLab })),
);

export function defineGamesRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/games",
    validateSearch: (search: Record<string, unknown>) => parseSearch(gameSearchSchema, search),
    component: GameWorld,
  });
}

/** Game World: the context spine resolves before the lazy workbench chunk. */
function GameWorld() {
  usePublishGameContext(useSearch({ from: "/games" }));
  return (
    <Suspense fallback={<LoadingPanel label="Opening Game World" />}>
      <GameLab />
    </Suspense>
  );
}
