import { createRoute, lazyRouteComponent, type AnyRoute } from "@tanstack/react-router";

/** Library home: definitions and scientific authority. */
export function defineLibraryRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/library",
    component: lazyRouteComponent(() => import("@/pages/library"), "LibraryHome"),
  });
}
