/**
 * Recent analytical contexts (per-viewer convenience).
 *
 * Each entry is a readable label plus the exact URL that reproduces the
 * context; the URL stays the authority, so a recent entry can never carry
 * analytical state the router would not accept. Storage failures (private
 * mode, blocked site data) degrade to an in-memory list.
 */

import { z } from "zod";
import { create } from "zustand";

import { WORLD_IDS, type WorldId } from "@/lib/worlds";

const STORAGE_KEY = "dynamis.recent-contexts.v1";
const LIMIT = 12;

const recentSchema = z.object({
  key: z.string(),
  world: z.enum(WORLD_IDS),
  title: z.string(),
  subtitle: z.string(),
  href: z.string().startsWith("/"),
  at: z.number(),
});
export type RecentContext = z.infer<typeof recentSchema>;

function readStored(): RecentContext[] {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = z.array(recentSchema).safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data.slice(0, LIMIT) : [];
  } catch {
    return [];
  }
}

function writeStored(entries: readonly RecentContext[]): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Storage unavailable: the in-memory list still serves this session.
  }
}

interface RecentState {
  readonly entries: readonly RecentContext[];
  record: (entry: RecentContext) => void;
  clear: () => void;
}

export const useRecentContexts = create<RecentState>()((set, get) => ({
  entries: readStored(),
  record: (entry) => {
    const current = get().entries;
    const existing = current.find((item) => item.key === entry.key);
    if (existing && existing.href === entry.href && existing.title === entry.title && existing.subtitle === entry.subtitle) {
      return;
    }
    const next = [entry, ...current.filter((item) => item.key !== entry.key)].slice(0, LIMIT);
    writeStored(next);
    set({ entries: next });
  },
  clear: () => {
    writeStored([]);
    set({ entries: [] });
  },
}));

/** Most recent context of one World, for continuity when switching Worlds. */
export function lastContextOf(entries: readonly RecentContext[], world: WorldId): RecentContext | null {
  return entries.find((entry) => entry.world === world) ?? null;
}

export function relativeTime(at: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}
