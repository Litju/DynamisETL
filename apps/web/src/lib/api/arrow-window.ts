/**
 * Arrow dense-window fetch.
 *
 * Dense windows cross the network as one Arrow IPC ArrayBuffer plus a compact
 * metadata header. The Arrow/Comlink worker can either decode columns or
 * prepare renderer buffers before returning data to the main thread.
 */

import { ApiError, apiBaseUrl } from "@/lib/api/client";
import type { DenseWindowMeta } from "@/api/types";
import { decodeWindowOffThread } from "@/lib/arrow/client";
import type { DecodedWindow } from "@/lib/arrow/decode";
import type { DenseWindow } from "@/api/types";
import { tableFromJson } from "@/lib/arrow/window-table";

export interface ArrowWindow {
  readonly meta: DenseWindowMeta;
  readonly decoded: DecodedWindow;
}

export interface PreparedArrowWindow<T> {
  readonly meta: DenseWindowMeta;
  readonly prepared: T;
}

export interface ArrowWindowParams {
  readonly fromNs?: number | undefined;
  readonly toNs?: number | undefined;
  readonly columns?: readonly string[] | undefined;
  readonly maxPoints?: number | undefined;
  readonly entityId?: string | undefined;
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

async function fetchArrowPayload(
  artifactId: string,
  params: ArrowWindowParams,
  signal?: AbortSignal,
): Promise<{ readonly meta: DenseWindowMeta; readonly buffer: ArrayBuffer }> {
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
    base + "/api/artifacts/" + encodeURIComponent(artifactId) + "/window?" + query,
    {
      headers: { Accept: "application/vnd.apache.arrow.stream" },
      ...(signal ? { signal } : {}),
    },
  );
  if (!response.ok) {
    // Older serving deployments expose only the JSON window route and answer
    // an Arrow-format request with 404; the JSON retry will preserve real
    // artifact errors while keeping this transport fallback compatible.
    if (response.status === 404 || response.status === 406 || response.status === 415) {
      throw new ArrowTransportUnsupportedError(
        "Arrow window transport is unsupported (" + response.status + ")",
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
      detail ?? "Arrow window request failed with status " + response.status,
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
  if (!header) throw new Error("arrow window response is missing its metadata header");
  return {
    meta: JSON.parse(header) as DenseWindowMeta,
    buffer: await response.arrayBuffer(),
  };
}

export async function fetchWindowArrow(
  artifactId: string,
  params: ArrowWindowParams,
  signal?: AbortSignal,
): Promise<ArrowWindow> {
  const { meta, buffer } = await fetchArrowPayload(artifactId, params, signal);
  return { meta, decoded: await decodeWindowOffThread(buffer) };
}

export async function fetchWindowArrowPrepared<T>(
  artifactId: string,
  params: ArrowWindowParams,
  prepare: (buffer: ArrayBuffer) => Promise<T>,
  signal?: AbortSignal,
  prepareJson?: (decoded: DecodedWindow) => Promise<T>,
): Promise<PreparedArrowWindow<T>> {
  try {
    const { meta, buffer } = await fetchArrowPayload(artifactId, params, signal);
    return { meta, prepared: await prepare(buffer) };
  } catch (error) {
    if (!(error instanceof ArrowTransportUnsupportedError) || prepareJson === undefined) throw error;
    const query = compact({
      from_ns: params.fromNs,
      to_ns: params.toNs,
      columns: params.columns?.join(","),
      max_points: params.maxPoints,
      entity_id: params.entityId,
    });
    const response = await fetch(
      apiBaseUrl().replace(/\/+$/, "") + "/api/artifacts/" + encodeURIComponent(artifactId) + "/window?" + query,
      { headers: { Accept: "application/json" }, ...(signal ? { signal } : {}) },
    );
    if (!response.ok) {
      let detail: string | undefined;
      let state: string | undefined;
      try {
        const payload = (await response.json()) as { detail?: unknown; state?: unknown };
        detail = typeof payload.detail === "string" ? payload.detail : undefined;
        state = typeof payload.state === "string" ? payload.state : undefined;
      } catch {
        // Keep the HTTP status when the response body is not JSON.
      }
      throw new ApiError(response.status, detail ?? "JSON window request failed with status " + response.status, state);
    }
    const json = (await response.json()) as DenseWindow;
    const table = tableFromJson(json);
    const decoded: DecodedWindow = {
      rowCount: table.rowCount,
      timeNs: table.timeNs,
      columns: [
        ...[...table.numeric].map(([name, values]) => ({ name, type: "Float64", numeric: true, values })),
        ...[...table.strings].map(([name, values]) => ({ name, type: "Utf8", numeric: false, values })),
      ],
    };
    return { meta: json.meta, prepared: await prepareJson(decoded) };
  }
}
