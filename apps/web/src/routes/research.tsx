import { createRoute, lazyRouteComponent, type AnyRoute } from "@tanstack/react-router";

/** Research Home: the page chunk loads on demand; the entry shell stays small. */
export function defineResearchRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/",
    component: lazyRouteComponent(() => import("@/pages/research"), "ResearchHome"),
  });
}
