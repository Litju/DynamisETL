/**
 * Arrow dense-window fetch.
 *
 * Dense windows prefer Arrow IPC (`format=arrow`): the payload crosses as a
 * single transferable buffer plus a compact JSON metadata header, and the decode
 * happens in the Arrow worker. JSON remains the metadata/small-payload path.
 */

import { apiBaseUrl } from "@/lib/api/client";
import type { DenseWindowMeta } from "@/api/types";
import { decodeWindowOffThread } from "@/lib/arrow/client";
import type { DecodedWindow } from "@/lib/arrow/decode";

export interface ArrowWindow {
  readonly meta: DenseWindowMeta;
  readonly decoded: DecodedWindow;
}

function compact(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  return search.toString();
}

export async function fetchWindowArrow(
  artifactId: string,
  params: {
    fromNs?: number;
    toNs?: number;
    columns?: readonly string[];
    maxPoints?: number;
    entityId?: string;
  },
  signal?: AbortSignal,
): Promise<ArrowWindow> {
  const query = compact({
    from_ns: params.fromNs,
    to_ns: params.toNs,
    columns: params.columns?.join(","),
    max_points: params.maxPoints,
    entity_id: params.entityId,
    format: "arrow",
  });
  const base = apiBaseUrl().replace(/\/+$/, "");
  const response = await fetch(
    `${base}/api/artifacts/${encodeURIComponent(artifactId)}/window?${query}`,
    {
      headers: { Accept: "application/vnd.apache.arrow.stream" },
      ...(signal ? { signal } : {}),
    },
  );
  if (!response.ok) {
    throw new Error(`arrow window request failed: ${response.status}`);
  }
  const header = response.headers.get("X-Dynamis-Window-Meta");
  if (!header) {
    throw new Error("arrow window response is missing its metadata header");
  }
  const meta = JSON.parse(header) as DenseWindowMeta;
  const buffer = await response.arrayBuffer();
  const decoded = await decodeWindowOffThread(buffer);
  return { meta, decoded };
}
