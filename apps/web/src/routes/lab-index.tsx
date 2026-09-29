import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { MatchNavigator } from "@/components/matchlab/MatchNavigator";
import { usePublishContext } from "@/lib/state/context";

/** `/lab` without a session: the Match World entry navigator (metadata only). */
export function defineLabIndexRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/lab",
    component: LabIndexPage,
  });
}

function LabIndexPage() {
  usePublishContext({
    owner: "match-entry",
    world: "match",
    crumbs: [{ key: "entry", label: "All matches", kind: "Match World entry" }],
  });
  return <MatchNavigator />;
}
