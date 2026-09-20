import { describe, expect, it } from "vitest";

import type { SessionDetail, StreamView } from "@/api/types";
import { datasetSurfaces, sessionSurfaces } from "@/lib/capabilities";
import { affordableSpanNs, windowAround } from "@/lib/dense-window";
import { defaultStreamFor, patchChangesSearch, resolveLabDefaults } from "@/lib/defaults";

function stream(overrides: Partial<StreamView> & Pick<StreamView, "stream_id" | "modality">) {
  return {
    measurement_class: "SOURCE_DERIVED",
    subject_id: null,
    trial_id: null,
    device_id: null,
    nominal_sampling_rate_hz: 100,
    si_units: ["1"],
    source_unit: "1",
    coordinate_frame_id: null,
    synchronization_spec_id: "sync",
    clock_id: "clock",
    skeleton_id: null,
    sample_artifact_ids: ["artifact"],
    sample_row_count: 10,
    ...overrides,
  } as StreamView;
}

function session(streams: StreamView[], trials: string[] = []): SessionDetail {
  return {
    dataset_id: "d",
    session: {
      session_id: "s",
      kind: "laboratory",
      label: null,
      started_at: null,
      ended_at: null,
      participant_count: 0,
      trial_count: trials.length,
      stream_count: streams.length,
    },
    participants: [],
    trials: trials.map((trial_id) => ({
      trial_id,
      subject_id: null,
      parent_trial_id: null,
      label: null,
      started_at: null,
      ended_at: null,
    })),
    streams,
  };
}

describe("capability derivation", () => {
  it("offers a laboratory only when a stream carries a canonical artifact", () => {
    expect(
      sessionSurfaces([
        stream({ stream_id: "force-1", modality: "force" }),
        stream({ stream_id: "pose-1", modality: "pose", sample_artifact_ids: [] }),
        stream({ stream_id: "track-1", modality: "tracking" }),
      ]),
    ).toEqual(["signals", "field"]);
  });

  it("never advertises a dataset laboratory with no ingested stream", () => {
    // GymAware declares an LPT modality but has no canonical stream.
    expect(datasetSurfaces(["lpt"], 0)).toEqual([]);
    expect(datasetSurfaces(["lpt"], 12)).toEqual(["signals"]);
  });

  it("treats event data as context, not as its own laboratory", () => {
    expect(sessionSurfaces([stream({ stream_id: "events", modality: "event" })])).toEqual([]);
  });
});

describe("deterministic laboratory defaults", () => {
  it("prefers force over inertial, then registry order", () => {
    const detail = session([
      stream({ stream_id: "imu-b", modality: "imu" }),
      stream({ stream_id: "force-b", modality: "force" }),
      stream({ stream_id: "force-a", modality: "force" }),
    ]);
    expect(defaultStreamFor(detail, "signals")?.stream_id).toBe("force-a");
  });

  it("selects a stream, trial and subject from the real session", () => {
    const detail = session(
      [
        stream({
          stream_id: "force-t0",
          modality: "force",
          trial_id: "t0",
          subject_id: "s0",
        }),
      ],
      ["t0"],
    );
    expect(resolveLabDefaults(detail, {}).patch).toEqual({
      view: "overview",
      stream: "force-t0",
      trial: "t0",
      subject: "s0",
    });
  });

  it("never invents a subject the data does not name", () => {
    const detail = session([stream({ stream_id: "pose-1", modality: "pose" })], ["p1"]);
    const { patch } = resolveLabDefaults(detail, { view: "pose" });
    expect(patch.subject).toBeUndefined();
    expect(patch.stream).toBe("pose-1");
  });

  it("lets an explicit deep link win over every default", () => {
    const detail = session(
      [
        stream({ stream_id: "force-a", modality: "force", trial_id: "t0" }),
        stream({ stream_id: "force-b", modality: "force", trial_id: "t1" }),
      ],
      ["t0", "t1"],
    );
    const deepLink = {
      view: "signals" as const,
      stream: "force-b",
      trial: "t1",
      subject: "chosen",
    };
    expect(patchChangesSearch(resolveLabDefaults(detail, deepLink).patch, deepLink)).toBe(false);
  });

  it("replaces a stream that cannot serve the visible surface", () => {
    const detail = session([
      stream({ stream_id: "force-a", modality: "force" }),
      stream({ stream_id: "track-a", modality: "tracking" }),
    ]);
    // A stale link points the field laboratory at a force stream.
    const { patch } = resolveLabDefaults(detail, { view: "field", stream: "force-a" });
    expect(patch.stream).toBe("track-a");
  });

  it("resolves to a stable result, so a deep link and a fresh open agree", () => {
    const detail = session(
      [
        stream({ stream_id: "imu-a", modality: "imu", trial_id: "t0" }),
        stream({ stream_id: "force-a", modality: "force", trial_id: "t0" }),
      ],
      ["t0"],
    );
    const first = resolveLabDefaults(detail, {}).patch;
    const second = resolveLabDefaults(detail, first).patch;
    expect(patchChangesSearch(second, first)).toBe(false);
  });
});

function artifact(rowCount: number, spanNs: number, entityCount: number | null) {
  return {
    row_count: rowCount,
    canonical_time_min_ns: 0,
    canonical_time_max_ns: spanNs,
    entity_count: entityCount,
  } as Parameters<typeof affordableSpanNs>[0];
}

describe("dense window sizing", () => {
  it("returns the whole recording when it already fits the budget", () => {
    // White CMJ force trial: 1,346 rows over 1.345 s.
    expect(affordableSpanNs(artifact(1346, 1_345_000_000, 1), { maxPoints: 4000 })).toBe(
      1_345_000_000n,
    );
  });

  it("shrinks the window as the artifact gets denser", () => {
    // SkillCorner tracking: 550k rows / 3023 s. DFL: 1.59M rows / 2765 s.
    const skillcorner = affordableSpanNs(artifact(549_999, 3_022_900_000_000, 24), {
      maxPoints: 20_000,
    });
    const dfl = affordableSpanNs(artifact(1_590_013, 2_765_200_000_000, 23), {
      maxPoints: 20_000,
    });
    expect(skillcorner).not.toBeNull();
    expect(dfl).not.toBeNull();
    expect(dfl!).toBeLessThan(skillcorner!);
  });

  it("divides by the entity count when the request is entity-scoped", () => {
    // SkillCorner pose: 21.4M rows over 3019 s across 23 subjects. Without
    // scoping no usable window exists; scoped to one subject it does.
    const pose = artifact(21_418_095, 3_018_680_000_000, 23);
    const unscoped = affordableSpanNs(pose, { maxPoints: 20_000 });
    const scoped = affordableSpanNs(pose, { maxPoints: 20_000, entityScoped: true });
    expect(scoped).not.toBeNull();
    expect(scoped!).toBeGreaterThan(unscoped!);
  });

  it("clamps the window inside the canonical bounds", () => {
    const bounds = windowAround(artifact(1_000_000, 100_000_000_000, 1), {
      anchorNs: 0n,
      explicit: null,
      maxPoints: 20_000,
    });
    expect(bounds).not.toBeNull();
    expect(bounds!.fromNs).toBe(0n);
    expect(bounds!.toNs).toBeLessThanOrEqual(100_000_000_000n);
    expect(bounds!.explicit).toBe(false);
  });

  it("always honours an explicitly committed range", () => {
    const bounds = windowAround(artifact(1_000_000, 100_000_000_000, 1), {
      anchorNs: 50_000_000_000n,
      explicit: { fromNs: 10n, toNs: 20n },
      maxPoints: 20_000,
    });
    expect(bounds).toEqual({ fromNs: 10n, toNs: 20n, explicit: true });
  });
});
