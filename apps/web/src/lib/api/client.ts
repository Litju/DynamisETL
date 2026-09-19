/**
 * Typed API client.
 *
 * FastAPI OpenAPI is the schema authority; `src/api/schema.d.ts` is generated
 * from it (`pnpm api:generate`) and this module only binds the generated types
 * to a same-origin fetch client. Hand-written DTO twins are forbidden.
 */

import createClient from "openapi-fetch";

import type { paths } from "@/api/schema";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly state?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface FetchResult<T> {
  readonly data?: T;
  readonly error?: unknown;
  readonly response: Response;
}

export function apiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (configured) return configured;
  // openapi-fetch requires an absolute base; same-origin is the product default
  // and the Vite dev server proxies /api to the local FastAPI process.
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "http://localhost";
}

export const api = createClient<paths>({
  baseUrl: apiBaseUrl(),
  // Defer to the current global fetch so tests and embedding can install a
  // transport without the client capturing one at module import time.
  fetch: (request) => globalThis.fetch(request),
});

/** Convert an openapi-fetch result into a value or a typed ApiError. */
export async function unwrap<T>(result: FetchResult<T>): Promise<T> {
  if (result.data !== undefined && result.response.ok) {
    return result.data;
  }
  const error = result.error;
  const detail =
    typeof error === "object" && error !== null && "detail" in error
      ? String((error as { detail: unknown }).detail)
      : undefined;
  const state =
    typeof error === "object" && error !== null && "state" in error
      ? String((error as { state: unknown }).state)
      : undefined;
  throw new ApiError(
    result.response.status,
    detail ?? `API request failed with status ${result.response.status}`,
    state,
  );
}
