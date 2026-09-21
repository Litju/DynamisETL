/**
 * Arrow dense-window fetch.
 *
 * Dense windows prefer Arrow IPC (`format=arrow`): the payload crosses as a
 * single transferable buffer plus a compact JSON metadata header, and the decode
 * happens in the Arrow worker. JSON remains the metadata/small-payload path.
 */

import { ApiError, apiBaseUrl } from "@/lib/api/client";
import type { DenseWindowMeta } from "@/api/types";
import { decodeWindowOffThread } from "@/lib/arrow/client";
import type { DecodedWindow } from "@/lib/arrow/decode";

export interface ArrowWindow {
  readonly meta: DenseWindowMeta;
  readonly decoded: DecodedWindow;
}

/** The server cannot provide Arrow here; callers may try the JSON transport. */
export class ArrowTransportUnsupportedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ArrowTransportUnsupportedError";
  }
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
    if (response.status === 406 || response.status === 415) {
      throw new ArrowTransportUnsupportedError(
        `Arrow window transport is unsupported (${response.status})`,
      );
    }
    let detail: string | undefined;
    let state: string | undefined;
    try {
      const payload = (await response.json()) as { detail?: unknown; state?: unknown };
      detail = typeof payload.detail === "string" ? payload.detail : undefined;
      state = typeof payload.state === "string" ? payload.state : undefined;
    } catch {
      // Keep the HTTP status as the useful error when the body is not JSON.
    }
    throw new ApiError(
      response.status,
      detail ?? `Arrow window request failed with status ${response.status}`,
      state,
    );
  }
  const mediaType = response.headers.get("content-type")?.split(";", 1)[0]?.trim();
  if (mediaType !== "application/vnd.apache.arrow.stream") {
    throw new ArrowTransportUnsupportedError(
      "Arrow window response did not negotiate an Arrow stream",
    );
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
