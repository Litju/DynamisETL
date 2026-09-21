import { describe, expect, it } from "vitest";

import {
  angleAt,
  boundsOf,
  cameraFor,
  extractFrames,
  frameIndexAt,
  landmarksAt,
  overlaysFromParameters,
  planarCentre,
  summarizeFrame,
  toViewerPoint,
  type PoseRow,
} from "@/components/pose/pose-model";

const ROWS: PoseRow[] = [
  { t_rel_ns: 0, subject_id: "s1", joint_name: "nose", is_available: true, x_m: 0, y_m: 0, z_m: 0.1, error_m: 0.02 },
  { t_rel_ns: 0, subject_id: "s1", joint_name: "lHip", is_available: true, x_m: 0, y_m: 0, z_m: -0.4, error_m: 0.03 },
  { t_rel_ns: 0, subject_id: "s1", joint_name: "lKnee", is_available: false, x_m: null, y_m: null, z_m: null, error_m: null },
  { t_rel_ns: 40_000_000, subject_id: "s1", joint_name: "nose", is_available: true, x_m: 0.1, y_m: 0, z_m: 0.1, error_m: 0.02 },
  { t_rel_ns: 40_000_000, subject_id: "s1", joint_name: "lHip", is_available: true, x_m: 0.1, y_m: 0, z_m: -0.4, error_m: 0.03 },
  { t_rel_ns: 80_000_000, subject_id: "s1", joint_name: "nose", is_available: false, x_m: null, y_m: null, z_m: null },
];

describe("pose landmark extraction", () => {
  const frames = extractFrames(ROWS);

  it("keeps only available finite landmarks and never imputes", () => {
    expect(frames).toHaveLength(3);
    expect(frames[0]?.landmarks.map((landmark) => landmark.jointName)).toEqual(["lHip", "nose"]);
    expect(frames[2]?.landmarks).toEqual([]);
    expect(frames[2]?.observed).toBe(false);
  });

  it("finds the frame at or before a canonical time", () => {
    expect(frameIndexAt(frames, 0n)).toBe(0);
    expect(frameIndexAt(frames, 39_999_999n)).toBe(0);
    expect(frameIndexAt(frames, 40_000_000n)).toBe(1);
    expect(frameIndexAt(frames, 10_000_000_000n)).toBe(2);
    expect(landmarksAt(frames, 40_000_000n).map((landmark) => landmark.jointName)).toEqual([
      "lHip",
      "nose",
    ]);
  });

  it("puts the centroid-relative vertical on the viewer's up axis", () => {
    // Source x/y are pitch-plane metres and source z is centroid-relative
    // height. Mapping them straight onto the renderer would lay the subject on
    // its side, so the viewer's up axis carries source z.
    const centre = planarCentre(frames[0]!.landmarks);
    expect(toViewerPoint({ xM: 1, yM: 3, zM: 3 }, { xM: 1, yM: 2 })).toEqual([0, 3, -1]);

    const bounds = boundsOf(frames[0]!.landmarks);
    // nose z = 0.1, hip z = -0.4, so the vertical midpoint is -0.15.
    expect(bounds.center[1]).toBeCloseTo(-0.15, 9);
    // Both landmarks sit at the same pitch-plane point, so the horizontal
    // extent is zero once the cloud is re-centred on its own origin.
    expect(centre).toEqual({ xM: 0, yM: 0 });
    expect(bounds.center[0]).toBeCloseTo(0, 9);
    expect(bounds.center[2]).toBeCloseTo(0, 9);
    expect(bounds.radius).toBeGreaterThan(0);
  });

  it("frames the observed cloud from every camera preset", () => {
    const bounds = boundsOf(frames[0]!.landmarks);
    const front = cameraFor("front", bounds);
    expect(front.target).toEqual(bounds.center);
    expect(front.position[2]).toBeGreaterThan(bounds.center[2]!);
    const left = cameraFor("left", bounds);
    expect(left.position[0]).toBeLessThan(bounds.center[0]!);
    const top = cameraFor("top", bounds);
    expect(top.position[1]).toBeGreaterThan(bounds.center[1]!);
    expect(cameraFor("reset", bounds).position).toEqual(cameraFor("free", bounds).position);
  });

  it("summarizes observed, unavailable and provider error context", () => {
    const summary = summarizeFrame(frames[0]!);
    expect(summary.observedLandmarks).toBe(2);
    expect(summary.unavailableLandmarks).toBe(1);
    expect(summary.landmarksWithError).toBe(2);
    expect(summary.meanErrorM).toBeCloseTo(0.025, 9);
    expect(summarizeFrame(null).unavailableLandmarks).toBe(0);
  });
});

describe("processor overlays", () => {
  it("reads segments and angles only from processor parameters", () => {
    const overlays = overlaysFromParameters({
      segments: [
        { name: "left_thigh", start_landmark: "lHip", end_landmark: "lKnee" },
        { name: "broken" },
      ],
      angles: [
        {
          name: "left_knee",
          vertex_landmark: "lKnee",
          first_landmark: "lHip",
          second_landmark: "lAnkle",
        },
      ],
    });
    expect(overlays.source).toBe("processor_parameters");
    expect(overlays.segments).toEqual([
      { name: "left_thigh", startLandmark: "lHip", endLandmark: "lKnee" },
    ]);
    expect(overlays.angles[0]?.vertexLandmark).toBe("lKnee");
  });

  it("never invents overlays when parameters declare none", () => {
    expect(overlaysFromParameters({}).source).toBe("none");
    expect(overlaysFromParameters(null).source).toBe("none");
    expect(overlaysFromParameters({ segments: [{ name: "x" }] }).source).toBe("none");
  });

  it("computes the three-point angle at the vertex", () => {
    const vertex = { jointName: "v", xM: 0, yM: 0, zM: 0, errorM: null };
    const first = { jointName: "a", xM: 1, yM: 0, zM: 0, errorM: null };
    const second = { jointName: "b", xM: 0, yM: 1, zM: 0, errorM: null };
    expect(angleAt(vertex, first, second)).toBeCloseTo(Math.PI / 2, 9);
  });
});
