/**
 * Shell context spine: the readable "where am I" that each screen publishes.
 *
 * The URL remains the analytical authority. A screen publishes only the
 * *display* projection of the context it already resolved (names, not ids)
 * so the global shell can show World, sport, competition, contest, period and
 * player without re-querying or guessing. A published context that is still
 * resolving says so (`pending`) instead of showing the previous World's names,
 * which is how stale values are kept out of the spine during transitions.
 */

import { useEffect } from "react";
import { create } from "zustand";

import type { LinkTarget, WorldId } from "@/lib/worlds";

export interface Crumb {
  readonly key: string;
  readonly label: string;
  /** Kind shown as a quiet prefix on hover/for screen readers. */
  readonly kind?: string | undefined;
  readonly target?: LinkTarget | undefined;
  /** Name not yet resolved: render geometry, never the old value. */
  readonly pending?: boolean | undefined;
}

/** Three separate readiness concepts, rendered side by side, never merged. */
export interface ContextReadiness {
  readonly upstream?: "available" | "unavailable" | undefined;
  readonly server?: "none" | "registered" | "materialized" | "ready" | undefined;
  readonly browser?: "loaded" | "loading" | "not-loaded" | undefined;
}

export interface PublishedContext {
  /** Owner key: changes whenever the durable identity changes. */
  readonly owner: string;
  readonly world: WorldId | null;
  readonly crumbs: readonly Crumb[];
  readonly readiness?: ContextReadiness | undefined;
  /** One-line title/subtitle used for Research "continue" entries. */
  readonly title?: string | undefined;
  readonly subtitle?: string | undefined;
}

interface ContextState {
  readonly context: PublishedContext | null;
  publish: (context: PublishedContext) => void;
  retract: (owner: string) => void;
}

function sameCrumbs(a: readonly Crumb[], b: readonly Crumb[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((crumb, index) => {
    const other = b[index]!;
    return crumb.key === other.key && crumb.label === other.label && crumb.pending === other.pending &&
      JSON.stringify(crumb.target ?? null) === JSON.stringify(other.target ?? null);
  });
}

function sameContext(a: PublishedContext | null, b: PublishedContext): boolean {
  return a !== null && a.owner === b.owner && a.world === b.world && a.title === b.title &&
    a.subtitle === b.subtitle && sameCrumbs(a.crumbs, b.crumbs) &&
    JSON.stringify(a.readiness ?? null) === JSON.stringify(b.readiness ?? null);
}

export const useShellContext = create<ContextState>()((set, get) => ({
  context: null,
  publish: (context) => {
    if (sameContext(get().context, context)) return;
    set({ context });
  },
  retract: (owner) => {
    if (get().context?.owner === owner) set({ context: null });
  },
}));

/** Publish this screen's readable context for the lifetime of the component. */
export function usePublishContext(context: PublishedContext | null): void {
  const publish = useShellContext((state) => state.publish);
  const retract = useShellContext((state) => state.retract);
  const serialized = context ? JSON.stringify(context) : null;
  useEffect(() => {
    if (serialized === null) return;
    const parsed = JSON.parse(serialized) as PublishedContext;
    publish(parsed);
  }, [publish, serialized]);
  const owner = context?.owner ?? null;
  useEffect(() => {
    if (owner === null) return;
    return () => retract(owner);
  }, [owner, retract]);
}
