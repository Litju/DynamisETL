import { Link, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  Boxes,
  Database,
  FileSearch,
  GitCompareArrows,
  ShieldCheck,
} from "lucide-react";

import { cn } from "@/lib/cn";

const NAV_ITEMS = [
  { to: "/catalog", label: "Catalog", icon: Database },
  { to: "/lab", label: "Laboratory", icon: Activity },
  { to: "/compare", label: "Compare", icon: GitCompareArrows },
  { to: "/methods", label: "Methodology", icon: FileSearch },
  { to: "/runs", label: "Processing runs", icon: Boxes },
  { to: "/quality", label: "Quality & rights", icon: ShieldCheck },
] as const;

/**
 * Activity rail (~48 px). Icon-only with accessible names and tooltips; the
 * active surface gets a structural marker, not just a color change.
 */
export function NavRail() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  return (
    <nav
      aria-label="Product surfaces"
      className="flex w-rail shrink-0 flex-col items-center gap-1 border-r border-border-subtle bg-surface-0 py-2"
    >
      <span
        className="mb-2 flex size-8 items-center justify-center rounded-control border border-border-strong text-[11px] font-semibold tracking-tight text-accent"
        title="DynamisData Performance Laboratory"
      >
        DD
      </span>
      {NAV_ITEMS.map((item) => {
        const active = pathname === item.to || pathname.startsWith(`${item.to}/`);
        const Icon = item.icon;
        return (
          <Link
            key={item.to}
            to={item.to}
            aria-label={item.label}
            title={item.label}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex size-8 items-center justify-center rounded-control text-text-muted transition-colors duration-quick hover:bg-surface-2 hover:text-text-secondary",
              active && "bg-surface-3 text-accent",
            )}
          >
            {active ? (
              <span
                aria-hidden="true"
                className="absolute left-0 h-4 w-0.5 -translate-x-1.5 bg-accent"
              />
            ) : null}
            <Icon size={16} strokeWidth={1.75} aria-hidden="true" />
          </Link>
        );
      })}
    </nav>
  );
}
