import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { MotionConfig } from "motion/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { router } from "@/router";
import { prefetchBootstrap } from "@/lib/use-catalog";
import "@/styles/index.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 15_000,
    },
  },
});

// Stage A: warm lightweight navigation metadata once, so Research, Data and
// entity-context drill-down answer from memory. Never dense data.
prefetchBootstrap(queryClient);

function Bootstrap() {
  return (
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <MotionConfig reducedMotion="user">
          <RouterProvider router={router} />
        </MotionConfig>
      </QueryClientProvider>
    </StrictMode>
  );
}

const container = document.getElementById("root");
if (container) {
  createRoot(container).render(<Bootstrap />);
}
