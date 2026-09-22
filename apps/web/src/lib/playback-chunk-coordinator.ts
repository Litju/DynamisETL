import {
  type QueryClient,
  type QueryKey,
  type QueryOptions,
} from "@tanstack/react-query";
import { useEffect, useId, useMemo, useSyncExternalStore } from "react";

import {
  planDenseChunks,
  type DenseChunkBounds,
  type DenseChunkPlan,
} from "@/lib/dense-chunks";
import { effectiveTimeNs, useAnalysisStore, type PlaybackStatus } from "@/lib/state/analysis";

export interface PlaybackChunkCoordinatorPort {
  isReady: (chunk: DenseChunkBounds) => boolean;
  prefetch: (chunk: DenseChunkBounds) => void;
  evict: (keep: ReadonlySet<string>) => void;
  cancel?: () => void;
}

export interface PlaybackChunkSnapshot {
  readonly plan: DenseChunkPlan | null;
  readonly status: PlaybackStatus;
  readonly waitingFor: DenseChunkBounds | null;
}

export interface PlaybackChunkCoordinatorOptions {
  readonly canonicalMinNs: bigint;
  readonly canonicalMaxNs: bigint;
  readonly chunkSpanNs: bigint;
  readonly anchorNs: bigint | null;
  readonly port: PlaybackChunkCoordinatorPort;
  readonly onEnded?: () => void;
}

type Listener = () => void;

/**
 * Shared boundary authority for prerecorded dense playback.
 *
 * The class is deliberately independent of React Query: tests can model
 * delayed chunks with a Set, while the hook below supplies the real cache.
 */
export class PlaybackChunkCoordinator {
  private readonly options: PlaybackChunkCoordinatorOptions;
  private readonly listeners = new Set<Listener>();
  private snapshot: PlaybackChunkSnapshot = {
    plan: null,
    status: "idle",
    waitingFor: null,
  };
  private timeNs: bigint | null = null;

  constructor(options: PlaybackChunkCoordinatorOptions) {
    this.options = options;
    this.timeNs = options.anchorNs;
    this.activate(this.planAt(options.anchorNs), options.anchorNs);
  }

  getSnapshot = (): PlaybackChunkSnapshot => this.snapshot;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Observe direct seeks and cache readiness without changing the URL. */
  observePlayhead(timeNs: bigint | null, playing: boolean): void {
    this.timeNs = timeNs;
    if (timeNs === null) return;
    const plan = this.planAt(timeNs);
    if (plan === null) return;
    if (this.snapshot.plan?.active.id !== plan.active.id) {
      this.activate(plan, timeNs);
    } else if (this.snapshot.status === "buffering") {
      this.refresh();
    } else if (this.snapshot.status === "ended" && timeNs !== this.boundForEnd(playing)) {
      this.setState({ status: "ready", waitingFor: null });
    }
  }

  /**
   * Gate one wall-clock step. A missing adjacent exact chunk clamps to the
   * canonical edge of the current chunk until the prefetch completes.
   */
  allowAdvance(fromNs: bigint, requestedNs: bigint): bigint {
    if (requestedNs === fromNs) return fromNs;
    const direction = requestedNs > fromNs ? 1 : -1;
    const bounded = clamp(requestedNs, this.options.canonicalMinNs, this.options.canonicalMaxNs);
    const currentPlan = this.planAt(fromNs);
    if (currentPlan === null) return bounded;
    if (this.snapshot.plan?.active.id !== currentPlan.active.id) {
      this.activate(currentPlan, fromNs);
    }
    if (!this.portReady(currentPlan.active)) {
      this.waitFor(currentPlan.active);
      return fromNs;
    }

    const targetPlan = this.planAt(bounded);
    if (targetPlan === null) return fromNs;
    if (targetPlan.active.id !== currentPlan.active.id) {
      if (!this.portReady(targetPlan.active)) {
        this.waitFor(targetPlan.active);
        this.prefetch(targetPlan);
        return direction > 0 ? currentPlan.active.toNs : currentPlan.active.fromNs;
      }
      this.activate(targetPlan, bounded);
    }

    if (bounded === this.options.canonicalMaxNs || bounded === this.options.canonicalMinNs) {
      this.setState({ status: "ended", waitingFor: null });
      this.options.onEnded?.();
    }
    return bounded;
  }

  /** Re-evaluate a blocked boundary after a query cache update. */
  refresh(): void {
    const waitingFor = this.snapshot.waitingFor;
    if (waitingFor !== null) {
      if (!this.portReady(waitingFor)) return;
      this.setState({ status: "ready", waitingFor: null });
      return;
    }
    const active = this.snapshot.plan?.active;
    if (active !== undefined && active !== null && this.portReady(active)) {
      this.setState({ status: "ready" });
    }
  }

  dispose(): void {
    this.options.port.cancel?.();
    this.listeners.clear();
  }

  private get port(): PlaybackChunkCoordinatorPort {
    return this.options.port;
  }

  private planAt(anchorNs: bigint | null): DenseChunkPlan | null {
    return planDenseChunks({
      canonicalMinNs: this.options.canonicalMinNs,
      canonicalMaxNs: this.options.canonicalMaxNs,
      anchorNs,
      chunkSpanNs: this.options.chunkSpanNs,
    });
  }

  private activate(plan: DenseChunkPlan | null, timeNs: bigint | null): void {
    if (plan === null) {
      this.setState({ plan: null, status: "idle", waitingFor: null });
      return;
    }
    const activeReady = this.portReady(plan.active);
    this.setState({
      plan,
      status: activeReady ? "ready" : "buffering",
      waitingFor: activeReady ? null : plan.active,
    });
    this.prefetch(plan);
    this.timeNs = timeNs;
  }

  private prefetch(plan: DenseChunkPlan): void {
    for (const chunk of [plan.active, plan.previous, plan.next]) {
      if (chunk !== null) this.port.prefetch(chunk);
    }
    this.port.evict(new Set([plan.active.id, plan.previous?.id, plan.next?.id].filter(Boolean) as string[]));
  }

  private portReady(chunk: DenseChunkBounds): boolean {
    return this.port.isReady(chunk);
  }

  private waitFor(chunk: DenseChunkBounds): void {
    this.setState({ status: "buffering", waitingFor: chunk });
  }

  private boundForEnd(playing: boolean): bigint | null {
    if (!playing || this.timeNs === null) return null;
    return this.timeNs === this.options.canonicalMinNs || this.timeNs === this.options.canonicalMaxNs
      ? this.timeNs
      : null;
  }

  private setState(next: Partial<PlaybackChunkSnapshot>): void {
    const updated = {
      plan: next.plan ?? this.snapshot.plan,
      status: next.status ?? this.snapshot.status,
      waitingFor: next.waitingFor === undefined ? this.snapshot.waitingFor : next.waitingFor,
    } satisfies PlaybackChunkSnapshot;
    if (
      updated.plan === this.snapshot.plan &&
      updated.status === this.snapshot.status &&
      updated.waitingFor === this.snapshot.waitingFor
    ) return;
    this.snapshot = updated;
    for (const listener of this.listeners) listener();
  }
}

const registered = new Set<PlaybackChunkCoordinator>();
const sharedCoordinators = new Map<
  string,
  { coordinator: PlaybackChunkCoordinator; owners: Set<string>; pendingReleases: Set<string> }
>();

function acquireSharedCoordinator(
  key: string,
  ownerId: string,
  create: () => PlaybackChunkCoordinator,
): PlaybackChunkCoordinator {
  const existing = sharedCoordinators.get(key);
  if (existing) {
    existing.owners.add(ownerId);
    existing.pendingReleases.delete(ownerId);
    return existing.coordinator;
  }
  const entry = {
    coordinator: create(),
    owners: new Set([ownerId]),
    pendingReleases: new Set<string>(),
  };
  sharedCoordinators.set(key, entry);
  return entry.coordinator;
}

function retainSharedCoordinator(key: string, coordinator: PlaybackChunkCoordinator, ownerId: string): void {
  const entry = sharedCoordinators.get(key);
  if (entry?.coordinator === coordinator) entry.pendingReleases.delete(ownerId);
}

function releaseSharedCoordinator(
  key: string,
  coordinator: PlaybackChunkCoordinator,
  ownerId: string,
  dispose: () => void,
): void {
  const entry = sharedCoordinators.get(key);
  if (!entry || entry.coordinator !== coordinator) {
    queueMicrotask(dispose);
    return;
  }
  entry.pendingReleases.add(ownerId);
  queueMicrotask(() => {
    if (!entry.pendingReleases.delete(ownerId)) return;
    entry.owners.delete(ownerId);
    if (entry.owners.size > 0 || sharedCoordinators.get(key) !== entry) return;
    sharedCoordinators.delete(key);
    dispose();
  });
}

/** Register the currently mounted dense surface with the global clock. */
export function registerPlaybackChunkCoordinator(
  coordinator: PlaybackChunkCoordinator,
): () => void {
  registered.add(coordinator);
  return () => registered.delete(coordinator);
}

/** Apply every mounted dense surface's boundary gate. */
export function constrainPlaybackAdvance(fromNs: bigint, requestedNs: bigint): bigint {
  let next = requestedNs;
  for (const coordinator of registered) next = coordinator.allowAdvance(fromNs, next);
  return next;
}

export function usePlaybackChunkCoordinator<T>(options: {
  readonly enabled: boolean;
  readonly canonicalMinNs: bigint | null;
  readonly canonicalMaxNs: bigint | null;
  readonly chunkSpanNs: bigint | null;
  readonly anchorNs: bigint | null;
  readonly queryClient: QueryClient;
  readonly coordinatorKey?: string;
  readonly queryOptionsFor: (chunk: DenseChunkBounds) => PlaybackChunkQueryOptions<T>;
  readonly isReady: (data: T | undefined) => boolean;
  readonly matchesQuery: (queryKey: QueryKey) => boolean;
  readonly chunkIdFromQueryKey: (queryKey: QueryKey) => string | null;
}): PlaybackChunkSnapshot & { readonly coordinator: PlaybackChunkCoordinator | null } {
  const ownerId = useId();
  const {
    enabled,
    canonicalMinNs,
    canonicalMaxNs,
    chunkSpanNs,
    anchorNs,
    queryClient,
    coordinatorKey,
    queryOptionsFor,
    isReady,
    matchesQuery,
    chunkIdFromQueryKey,
  } = options;
  const coordinatorToken = `${coordinatorKey ?? "local"}:${ownerId}`;
  const coordinator = useMemo(() => {
    if (
      !enabled ||
      canonicalMinNs === null ||
      canonicalMaxNs === null ||
      chunkSpanNs === null
    ) return null;
    const port: PlaybackChunkCoordinatorPort = {
      isReady: (chunk) => {
        const query = queryOptionsFor(chunk);
        return isReady(queryClient.getQueryData<T>(query.queryKey));
      },
      prefetch: (chunk) => {
        const query = queryOptionsFor(chunk);
        void queryClient.prefetchQuery({
          ...query,
          meta: { ...query.meta, playbackCoordinatorId: coordinatorToken },
        });
      },
      evict: (keep) => {
        queryClient.removeQueries({
          predicate: (query) =>
            matchesQuery(query.queryKey) &&
            !keep.has(chunkIdFromQueryKey(query.queryKey) ?? ""),
        });
      },
      cancel: () => {
        void queryClient.cancelQueries({
          predicate: (query) => query.meta?.playbackCoordinatorId === coordinatorToken,
        });
      },
    };
    const create = () => new PlaybackChunkCoordinator({
      canonicalMinNs,
      canonicalMaxNs,
      chunkSpanNs,
      anchorNs,
      port,
      onEnded: () => useAnalysisStore.getState().setPlaying(false),
    });
    return coordinatorKey ? acquireSharedCoordinator(coordinatorKey, ownerId, create) : create();
  }, [
    anchorNs,
    canonicalMaxNs,
    canonicalMinNs,
    chunkSpanNs,
    enabled,
    chunkIdFromQueryKey,
    isReady,
    matchesQuery,
    queryClient,
    queryOptionsFor,
    coordinatorKey,
    coordinatorToken,
    ownerId,
  ]);

  const snapshot = useSyncExternalStore(
    coordinator?.subscribe ?? emptySubscribe,
    coordinator?.getSnapshot ?? (() => emptySnapshot),
    coordinator?.getSnapshot ?? (() => emptySnapshot),
  );

  useEffect(() => {
    if (!coordinator) return;
    if (coordinatorKey) retainSharedCoordinator(coordinatorKey, coordinator, ownerId);
    const unregister = registerPlaybackChunkCoordinator(coordinator);
    const unsubscribeStore = useAnalysisStore.subscribe((state, previous) => {
      const next = effectiveTimeNs(state);
      const before = effectiveTimeNs(previous);
      if (next !== before || state.playing !== previous.playing) {
        coordinator.observePlayhead(next, state.playing);
      }
    });
    const unsubscribeCache = queryClient.getQueryCache().subscribe(() => coordinator.refresh());
    coordinator.observePlayhead(effectiveTimeNs(useAnalysisStore.getState()), useAnalysisStore.getState().playing);
    return () => {
      unsubscribeStore();
      unsubscribeCache();
      const dispose = () => {
        unregister();
        coordinator.dispose();
        if (registered.size === 0) useAnalysisStore.getState().setPlaybackStatus("idle");
      };
      if (coordinatorKey) releaseSharedCoordinator(coordinatorKey, coordinator, ownerId, dispose);
      else dispose();
    };
  }, [coordinator, coordinatorKey, ownerId, queryClient]);

  useEffect(() => {
    useAnalysisStore.getState().setPlaybackStatus(snapshot.status);
  }, [snapshot.status]);

  return { ...snapshot, coordinator };
}

const emptySnapshot: PlaybackChunkSnapshot = { plan: null, status: "idle", waitingFor: null };
const emptySubscribe = (_listener: Listener): (() => void) => () => undefined;

export type PlaybackChunkQueryOptions<T> = Omit<QueryOptions<T>, "queryKey" | "queryFn"> & {
  readonly queryKey: QueryKey;
  readonly queryFn: NonNullable<QueryOptions<T>["queryFn"]>;
};

function clamp(value: bigint, lower: bigint, upper: bigint): bigint {
  return value < lower ? lower : value > upper ? upper : value;
}
