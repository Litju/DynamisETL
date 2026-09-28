/**
 * Browser-side readiness: what analytical data is actually loaded in this
 * session's query cache.
 *
 * This is the third readiness fact (after upstream and server). It is read
 * from the TanStack Query cache, never inferred from metadata, and is
 * reactive so a context flips to "loaded" the moment its first dense window
 * resolves — and back when bounded eviction drops it.
 */

import { notifyManager, useQueryClient, type Query, type QueryClient } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";

const DENSE_SCOPES = new Set(["dense-window", "dense-chunk", "dense-chunk-window"]);

function isDense(query: Query): boolean {
  const scope = query.queryKey[0];
  return typeof scope === "string" && DENSE_SCOPES.has(scope);
}

export interface DenseCacheSummary {
  /** Distinct dense artifacts with at least one resolved window. */
  readonly artifacts: number;
  /** Resolved dense windows/chunks held in cache. */
  readonly windows: number;
  readonly fetching: number;
}

export function denseCacheSummary(client: QueryClient): DenseCacheSummary {
  const artifacts = new Set<string>();
  let windows = 0;
  let fetching = 0;
  for (const query of client.getQueryCache().getAll()) {
    if (!isDense(query)) continue;
    if (query.state.fetchStatus === "fetching") fetching += 1;
    if (query.state.status === "success" && query.state.data !== undefined) {
      windows += 1;
      artifacts.add(String(query.queryKey[1]));
    }
  }
  return { artifacts: artifacts.size, windows, fetching };
}

/** Loaded state for a set of artifacts (e.g. one session's streams). */
export function artifactsLoadState(
  client: QueryClient,
  artifactIds: ReadonlySet<string>,
): "loaded" | "loading" | "not-loaded" {
  if (artifactIds.size === 0) return "not-loaded";
  let loading = false;
  for (const query of client.getQueryCache().getAll()) {
    if (!isDense(query)) continue;
    if (!artifactIds.has(String(query.queryKey[1]))) continue;
    if (query.state.status === "success" && query.state.data !== undefined) return "loaded";
    if (query.state.fetchStatus === "fetching") loading = true;
  }
  return loading ? "loading" : "not-loaded";
}

function useCacheSnapshot<T>(read: (client: QueryClient) => T, serialize: (value: T) => string): T {
  const client = useQueryClient();
  // Query-cache events fire synchronously while other components render (a
  // query is created during render); batch them like useQuery does so this
  // store never updates a component mid-render of another.
  const subscribe = useCallback(
    (onChange: () => void) => client.getQueryCache().subscribe(notifyManager.batchCalls(() => onChange())),
    [client],
  );
  // useSyncExternalStore needs a stable snapshot identity; serialize the
  // small summary so unrelated cache events do not re-render consumers.
  const snapshot = useSyncExternalStore(
    subscribe,
    () => serialize(read(client)),
    () => serialize(read(client)),
  );
  return JSON.parse(snapshot) as T;
}

/** Load state of any query family by key prefix (e.g. one game's court frames). */
export function useKeyLoadState(prefix: readonly unknown[]): "loaded" | "loading" | "not-loaded" {
  const key = JSON.stringify(prefix);
  const read = useCallback(
    (client: QueryClient) => {
      const parsed = JSON.parse(key) as unknown[];
      let loading = false;
      for (const query of client.getQueryCache().findAll({ queryKey: parsed })) {
        if (query.state.status === "success" && query.state.data !== undefined) return "loaded" as const;
        if (query.state.fetchStatus === "fetching") loading = true;
      }
      return loading ? ("loading" as const) : ("not-loaded" as const);
    },
    [key],
  );
  return useCacheSnapshot(read, (value) => JSON.stringify(value));
}

export function useDenseCacheSummary(): DenseCacheSummary {
  return useCacheSnapshot(denseCacheSummary, (value) => JSON.stringify(value));
}

export function useArtifactsLoadState(artifactIds: readonly string[]): "loaded" | "loading" | "not-loaded" {
  const key = [...artifactIds].sort().join("|");
  const read = useCallback(
    (client: QueryClient) => artifactsLoadState(client, new Set(key ? key.split("|") : [])),
    [key],
  );
  return useCacheSnapshot(read, (value) => JSON.stringify(value));
}
