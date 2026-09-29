import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * Editorial page frame for hierarchy-boundary screens (Research, Data,
 * entity context, Library). Analytical Worlds never use it: their workbench
 * owns the full viewport.
 */
export function Page({
  label,
  children,
  className,
  width = "wide",
}: {
  label: string;
  children: ReactNode;
  className?: string;
  width?: "wide" | "full";
}) {
  return (
    <section aria-label={label} className="d-atmosphere cq-page h-full min-w-0 flex-1 overflow-y-auto">
      <div
        className={cn(
          "mx-auto w-full px-8 pb-20 pt-9 max-[1400px]:px-6 max-[1400px]:pt-7",
          width === "wide" ? "max-w-[78rem]" : "max-w-none",
          className,
        )}
      >
        {children}
      </div>
    </section>
  );
}

export function PageHeader({
  kicker,
  title,
  lede,
  actions,
  meta,
  className,
}: {
  kicker?: ReactNode;
  title: ReactNode;
  lede?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-end justify-between gap-x-8 gap-y-4", className)}>
      <div className="min-w-0 max-w-3xl">
        {kicker ? <div className="t-kicker mb-3 flex items-center gap-2">{kicker}</div> : null}
        <h1 className="t-display" style={{ viewTransitionName: "d-entity-title" }}>
          {title}
        </h1>
        {lede ? <p className="t-lede mt-3 max-w-2xl">{lede}</p> : null}
        {meta ? <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">{meta}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** Numbered editorial section label with a hairline and an optional action. */
export function SectionHeader({
  index,
  title,
  detail,
  action,
  id,
  className,
}: {
  index?: string;
  title: ReactNode;
  detail?: ReactNode;
  action?: ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <div className={cn("mb-3 flex items-baseline gap-3", className)}>
      {index ? <span className="t-kicker w-5 shrink-0 text-text-faint">{index}</span> : null}
      <h2 id={id} className="shrink-0 text-[13px] font-semibold tracking-[-0.01em] text-text-primary">
        {title}
      </h2>
      {detail ? <span className="truncate text-[11.5px] text-text-muted">{detail}</span> : null}
      <span aria-hidden="true" className="d-rule min-w-6 flex-1 self-center" />
      {action ? <span className="shrink-0 text-[11.5px]">{action}</span> : null}
    </div>
  );
}

/** A quiet key/value readout with a monospaced value. */
export function Readout({
  label,
  value,
  detail,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="t-kicker mb-1.5">{label}</div>
      <div className="mono text-[20px] font-medium leading-none tracking-[-0.02em] text-text-primary tabular">{value}</div>
      {detail ? <div className="mt-1.5 text-[11px] text-text-muted">{detail}</div> : null}
    </div>
  );
}
