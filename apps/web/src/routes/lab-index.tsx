import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { StatePanel } from "@/components/common/StatePanel";


/** `/lab` without a session: an explicit empty state, never a mock laboratory. */
export function defineLabIndexRoute(parent: AnyRoute) {
  return createRoute({
  getParentRoute: () => parent,
  path: "/lab",
  component: LabIndexPage,
});
}

function LabIndexPage() {
  return (
    <StatePanel
      state="empty"
      title="No session open."
      detail="Open the Catalog and choose a dataset session to enter the laboratory. Durable analysis context (trial, subject, time, range, view) is carried in the URL."
    />
  );
}
