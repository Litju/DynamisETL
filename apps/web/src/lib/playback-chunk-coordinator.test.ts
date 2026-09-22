import { describe, expect, it } from "vitest";

import {
  PlaybackChunkCoordinator,
  type PlaybackChunkCoordinatorPort,
} from "@/lib/playback-chunk-coordinator";

function harness() {
  const ready = new Set<string>();
  const prefetched: string[] = [];
  const evicted: string[][] = [];
  const port: PlaybackChunkCoordinatorPort = {
    isReady: (chunk) => ready.has(chunk.id),
    prefetch: (chunk) => prefetched.push(chunk.id),
    evict: (keep) => evicted.push([...keep].sort()),
  };
  const coordinator = new PlaybackChunkCoordinator({
    canonicalMinNs: 0n,
    canonicalMaxNs: 99n,
    chunkSpanNs: 20n,
    anchorNs: 5n,
    port,
  });
  return { coordinator, ready, prefetched, evicted };
}

function id(from: number, to: number): string {
  return `${from}..${to}`;
}

describe("PlaybackChunkCoordinator", () => {
  it("hands forward playback across three non-overlapping boundaries", () => {
    const { coordinator, ready } = harness();
    ready.add(id(0, 19));
    coordinator.refresh();
    expect(coordinator.allowAdvance(5n, 19n)).toBe(19n);

    const next = id(20, 39);
    expect(coordinator.allowAdvance(19n, 20n)).toBe(19n);
    ready.add(next);
    coordinator.refresh();
    expect(coordinator.allowAdvance(19n, 20n)).toBe(20n);
    expect(coordinator.getSnapshot().plan?.active.id).toBe(next);

    const third = id(40, 59);
    expect(coordinator.allowAdvance(39n, 40n)).toBe(39n);
    ready.add(third);
    coordinator.refresh();
    expect(coordinator.allowAdvance(39n, 40n)).toBe(40n);
    expect(coordinator.getSnapshot().plan?.active.id).toBe(third);
  });

  it("buffers reverse playback and re-plans a seek", () => {
    const { coordinator, ready } = harness();
    ready.add(id(0, 19));
    ready.add(id(20, 39));
    coordinator.refresh();
    expect(coordinator.allowAdvance(25n, 19n)).toBe(19n);
    expect(coordinator.allowAdvance(19n, 18n)).toBe(18n);

    coordinator.observePlayhead(75n, false);
    expect(coordinator.getSnapshot().plan?.active.id).toBe(id(60, 79));
    expect(coordinator.getSnapshot().status).toBe("buffering");
    ready.add(id(60, 79));
    coordinator.refresh();
    expect(coordinator.getSnapshot().status).toBe("ready");
  });

  it("allows reverse playback to leave the canonical maximum", () => {
    const { coordinator, ready } = harness();
    ready.add(id(0, 19));
    ready.add(id(20, 39));
    ready.add(id(40, 59));
    ready.add(id(60, 79));
    ready.add(id(80, 99));
    coordinator.observePlayhead(99n, false);
    expect(coordinator.allowAdvance(99n, 98n)).toBe(98n);
  });

  it("prefetches and retains only previous/active/next", () => {
    const { prefetched, evicted } = harness();
    expect(prefetched).toContain(id(0, 19));
    expect(prefetched).toContain(id(20, 39));
    expect(evicted.at(-1)).toEqual([id(0, 19), id(20, 39)]);
  });
});
