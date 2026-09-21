import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * One analytical panel frame: subdued chrome, one-pixel separators, internal
 * scrolling, optional header actions. Scientific content owns the surface.
 */
export function Panel({
  title,
  id,
  actions,
  children,
  className,
  bodyClassName,
  role,
}: {
  title?: ReactNode;
  id?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  role?: string;
}) {
  return (
    <section
      id={id}
      role={role}
      aria-label={typeof title === "string" ? title : undefined}
      className={cn("flex min-h-0 flex-col bg-surface-1", className)}
    >
      {title ? (
        <header className="flex h-8 shrink-0 items-center justify-between gap-2 border-b border-border-subtle px-3">
          <h2 className="t-section truncate text-text-muted">
            {title}
          </h2>
          {actions ? <div className="flex items-center gap-1">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn("min-h-0 flex-1 overflow-auto", bodyClassName)}>{children}</div>
    </section>
  );
}

export function KeyValueRow({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] items-baseline gap-2 border-b border-border-subtle/60 px-3 py-1.5 last:border-b-0">
          <dt className="t-section text-text-muted">{label}</dt>
      <dd className={cn("min-w-0 break-words text-[12px] text-text-secondary", mono && "mono")}>
        {children}
      </dd>
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="t-section mb-2 text-text-muted">
      {children}
    </h3>
  );
}
