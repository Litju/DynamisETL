import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { MatchNavigator } from "@/components/matchlab/MatchNavigator";


/** `/lab` without a session: an explicit empty state, never a mock laboratory. */
export function defineLabIndexRoute(parent: AnyRoute) {
  return createRoute({
  getParentRoute: () => parent,
  path: "/lab",
  component: LabIndexPage,
});
}

function LabIndexPage() {
  return <MatchNavigator />;
}
