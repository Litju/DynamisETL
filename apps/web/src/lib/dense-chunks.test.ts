import { describe, expect, it } from "vitest";

import { denseChunkId, planDenseChunks } from "@/lib/dense-chunks";

describe("planDenseChunks", () => {
  it("creates non-overlapping deterministic previous/active/next chunks", () => {
    const plan = planDenseChunks({
      canonicalMinNs: 0n,
      canonicalMaxNs: 99n,
      anchorNs: 45n,
      chunkSpanNs: 20n,
    });
    expect(plan).not.toBeNull();
    if (!plan) return;
    expect(plan.active).toEqual({ fromNs: 40n, toNs: 59n, id: denseChunkId(40n, 59n) });
    expect(plan.previous?.toNs).toBe(39n);
    expect(plan.next?.fromNs).toBe(plan.active.toNs + 1n);
  });

  it("clamps an anchor and does not create an empty adjacent chunk", () => {
    const plan = planDenseChunks({
      canonicalMinNs: 0n,
      canonicalMaxNs: 9n,
      anchorNs: 999n,
      chunkSpanNs: 20n,
    });
    expect(plan).toEqual({ active: { fromNs: 0n, toNs: 9n, id: denseChunkId(0n, 9n) }, previous: null, next: null });
  });
});
