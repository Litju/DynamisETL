import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * Fixed-row virtual list for long catalog lists (games, players, sessions).
 *
 * TanStack Virtual owns the visible window; `onNearEnd` requests the next
 * bounded page when the viewport approaches the loaded tail, so continuation
 * is driven by what the reader scrolls to — never by what merely exists.
 */
export function VirtualList<T>({
  items,
  rowHeight,
  getKey,
  renderRow,
  onNearEnd,
  className,
  ariaLabel,
  role = "list",
  children,
}: {
  items: readonly T[];
  rowHeight: number;
  getKey: (item: T, index: number) => string;
  renderRow: (item: T, index: number, style: CSSProperties) => ReactNode;
  onNearEnd?: (() => void) | undefined;
  className?: string;
  ariaLabel: string;
  role?: "list" | "listbox";
  /** Rendered above the rows inside the scroller (skeletons, empty states). */
  children?: ReactNode;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // eslint-disable-next-line react-hooks/incompatible-library -- the virtualizer is read during render only
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 10,
  });
  const virtualItems = virtualizer.getVirtualItems();
  const lastIndex = virtualItems.at(-1)?.index ?? -1;
  useEffect(() => {
    if (onNearEnd && items.length > 0 && lastIndex >= items.length - 20) onNearEnd();
  }, [items.length, lastIndex, onNearEnd]);

  return (
    <div ref={scrollRef} className={cn("overflow-y-auto", className)} role={role} aria-label={ariaLabel}>
      {children}
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualItems.map((item) => (
          <div key={getKey(items[item.index]!, item.index)} role={role === "list" ? "listitem" : "presentation"} style={{ position: "absolute", top: 0, left: 0, right: 0, height: item.size, transform: `translateY(${item.start}px)` }}>
            {renderRow(items[item.index]!, item.index, { height: "100%" })}
          </div>
        ))}
      </div>
    </div>
  );
}
