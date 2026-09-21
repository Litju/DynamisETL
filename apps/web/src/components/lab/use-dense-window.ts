import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { fetchWindowArrow } from "@/lib/api/arrow-window";
import {
  tableFromDecoded,
  tableFromJson,
  type WindowTable,
} from "@/lib/arrow/window-table";
import type { DenseWindowMeta } from "@/api/types";

export interface DenseWindowRequest {
  readonly artifactId: string | null;
  readonly fromNs?: number | undefined;
  readonly toNs?: number | undefined;
  readonly columns?: readonly string[] | undefined;
  readonly maxPoints?: number | undefined;
}

export interface DenseWindowState {
  readonly table: WindowTable | null;
  readonly transport: "arrow" | "json" | null;
  readonly meta: DenseWindowMeta | null;
}

/**
 * Dense window transport with an explicit preference order: Arrow IPC decoded
 * in the worker, JSON as the metadata/small-payload fallback. The transport in
 * use is reported so the surface can state how it received the data.
 */
export function useDenseWindow(request: DenseWindowRequest) {
  const query = useQuery({
    queryKey: [
      "dense-window",
      request.artifactId,
      request.fromNs ?? null,
      request.toNs ?? null,
      request.columns?.join(",") ?? null,
      request.maxPoints ?? null,
    ],
    enabled: Boolean(request.artifactId),
    queryFn: async (): Promise<DenseWindowState> => {
      const artifactId = request.artifactId ?? "";
      try {
        const arrow = await fetchWindowArrow(artifactId, {
          ...(request.fromNs !== undefined ? { fromNs: request.fromNs } : {}),
          ...(request.toNs !== undefined ? { toNs: request.toNs } : {}),
          ...(request.columns !== undefined ? { columns: request.columns } : {}),
          ...(request.maxPoints !== undefined ? { maxPoints: request.maxPoints } : {}),
        });
        return {
          table: tableFromDecoded(arrow.decoded, arrow.meta),
          transport: "arrow",
          meta: arrow.meta,
        };
      } catch {
        const json = await unwrap(
          await api.GET("/api/artifacts/{artifact_id}/window", {
            params: {
              path: { artifact_id: artifactId },
              query: {
                ...(request.fromNs !== undefined ? { from_ns: request.fromNs } : {}),
                ...(request.toNs !== undefined ? { to_ns: request.toNs } : {}),
                ...(request.columns !== undefined ? { columns: request.columns.join(",") } : {}),
                ...(request.maxPoints !== undefined ? { max_points: request.maxPoints } : {}),
              },
            },
          }),
        );
        return { table: tableFromJson(json), transport: "json", meta: json.meta };
      }
    },
    staleTime: 30_000,
  });
  return query;
}
