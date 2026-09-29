import { Link, useRouterState } from "@tanstack/react-router";
import { LayoutGroup, motion } from "motion/react";

import { cn } from "@/lib/cn";
import { usePublishContext } from "@/lib/state/context";

const ITEMS = [
  { to: "/library", label: "Overview" },
  { to: "/methods", label: "Metrics & methods" },
  { to: "/runs", label: "Runs & provenance" },
  { to: "/quality", label: "Quality & rights" },
] as const;

/**
 * Library sub-navigation. Library holds definitions and scientific
 * authority (what a result means, how it was computed, under which rights);
 * observations stay in Data.
 */
export function LibraryNav() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const active = ITEMS.find((item) => item.to === pathname) ?? ITEMS[0];
  usePublishContext({
    owner: `library:${active.to}`,
    world: null,
    crumbs: [
      { key: "library", label: "Library", kind: "Section", target: { to: "/library" } },
      ...(active.to !== "/library" ? [{ key: "page", label: active.label, kind: "Library" }] : []),
    ],
  });
  return (
    <LayoutGroup id="library-nav">
      <nav aria-label="Library" className="flex h-10 shrink-0 items-center gap-1 border-b border-border-subtle bg-surface-0 px-4">
        {ITEMS.map((item) => {
          const current = item.to === pathname;
          return (
            <Link
              key={item.to}
              to={item.to}
              aria-current={current ? "page" : undefined}
              className={cn(
                "relative flex h-10 items-center px-2.5 text-[12px] transition-colors duration-quick",
                current ? "font-medium text-text-primary" : "text-text-muted hover:text-text-secondary",
              )}
            >
              {item.label}
              {current ? (
                <motion.span
                  layoutId="library-underline"
                  transition={{ duration: 0.22, ease: [0.3, 0, 0, 1] }}
                  aria-hidden="true"
                  className="absolute inset-x-2.5 bottom-0 h-[2px] rounded-full bg-accent"
                />
              ) : null}
            </Link>
          );
        })}
      </nav>
    </LayoutGroup>
  );
}
