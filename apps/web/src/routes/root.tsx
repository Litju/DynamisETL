import { createRootRoute, Outlet, redirect } from "@tanstack/react-router";
import { useEffect } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { AnalysisContextProvider } from "@/lib/analysis-context-provider";
import { applyTheme, useUiStore } from "@/lib/state/ui";
import { NotFoundPage } from "@/routes/not-found";

function RootLayout() {
  const theme = useUiStore((state) => state.theme);
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  return (
    <AnalysisContextProvider>
      <AppShell>
        <Outlet />
      </AppShell>
    </AnalysisContextProvider>
  );
}

/**
 * Build a fresh root route for one router instance.
 *
 * Route instances are single-router in TanStack Router, and tests create a
 * memory router per case, so the tree is assembled through factories instead of
 * module-level singletons.
 */
export function defineRootRoute() {
  return createRootRoute({
    beforeLoad: ({ location }) => {
      if (location.pathname === "/") {
        throw redirect({ to: "/catalog" });
      }
    },
    component: RootLayout,
    notFoundComponent: NotFoundPage,
  });
}
