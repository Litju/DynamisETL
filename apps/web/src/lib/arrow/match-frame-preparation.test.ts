import { describe, expect, it } from "vitest";

import type { DecodedWindow } from "@/lib/arrow/decode";
import { poseFramesFromBuffers } from "@/components/pose/pose-model";
import {
  prepareEventWindow,
  preparePoseWindow,
  prepareTacticalGridWindow,
  prepareTacticalPolygonWindow,
  prepareTrackingWindow,
} from "@/lib/arrow/match-frame-preparation";

function decoded(
  times: readonly bigint[],
  columns: DecodedWindow["columns"],
): DecodedWindow {
  return {
    rowCount: times.length,
    timeNs: BigInt64Array.from(times),
    columns,
  };
}

function strings(name: string, values: string[]) {
  return { name, type: "Utf8", numeric: false, values };
}

function numbers(name: string, values: number[]) {
  return { name, type: "Float64", numeric: true, values: Float64Array.from(values) };
}

describe("Arrow MatchFrame preparation", () => {
  it("groups tracking rows by canonical time and transfers typed identities and quality", () => {
    const result = prepareTrackingWindow(
      decoded(
        [200n, 100n, 100n],
        [
          strings("object_id", ["p2", "ball", "p1"]),
          strings("object_type", ["player", "ball", "goalkeeper"]),
          strings("group_id", ["away", "", "home"]),
          numbers("x_m", [2, 4, 1]),
          numbers("y_m", [3, 5, 2]),
          strings("is_detected", ["false", "true", ""]),
        ],
      ),
    );

    expect([...result.frameTimesNs]).toEqual([100n, 200n]);
    expect([...result.frameOffsets]).toEqual([0, 2, 3]);
    expect(result.entityIds).toEqual(["ball", "p1", "p2"]);
    expect([...result.positionsXY]).toEqual([4, 5, 1, 2, 2, 3]);
    expect([...result.objectKinds]).toEqual([2, 1, 0]);
    expect([...result.detectionState]).toEqual([1, -1, 0]);
  });

  it("keeps source skeleton order, per-subject frames and unavailable masks", () => {
    const result = preparePoseWindow(
      decoded(
        [40n, 0n, 0n],
        [
          strings("subject_id", ["s2", "s1", "s1"]),
          strings("joint_name", ["nose", "lHip", "nose"]),
          strings("is_available", ["true", "true", "false"]),
          numbers("x_m", [4, 1, Number.NaN]),
          numbers("y_m", [5, 2, Number.NaN]),
          numbers("z_m", [6, 3, Number.NaN]),
          numbers("error_m", [0.04, 0.01, Number.NaN]),
        ],
      ),
      ["nose", "lHip"],
    );

    expect(result.subjectIds).toEqual(["s1", "s2"]);
    expect([...result.subjectFrameOffsets]).toEqual([0, 1, 2]);
    expect([...result.frameTimesNs]).toEqual([0n, 40n]);
    expect([...result.present]).toEqual([1, 1, 1, 0]);
    expect([...result.availability]).toEqual([0, 1, 1, 0]);
    expect([...result.positionsXYZ.slice(3, 6)]).toEqual([1, 2, 3]);
    expect(Number.isNaN(result.errorM[0])).toBe(true);
    expect(result.errorM[1]).toBeCloseTo(0.01);
    expect(result.errorM[2]).toBeCloseTo(0.04);
    expect(Number.isNaN(result.errorM[3])).toBe(true);
    expect(poseFramesFromBuffers(result, "s1")[0]).toMatchObject({
      unavailableJoints: ["nose"],
      landmarks: [{ jointName: "lHip", xM: 1, yM: 2, zM: 3 }],
    });
    expect(poseFramesFromBuffers(result, "s2")[0]?.unavailableJoints).toEqual([]);
  });

  it("parses exact tactical polygons into frame and point offsets", () => {
    const result = prepareTacticalPolygonWindow(
      decoded(
        [100n, 100n, 200n],
        [
          strings("group_id", ["home", "away", "home"]),
          strings("hull_polygon_json", [
            "[[0,0],[1,0],[1,1]]",
            "[[2,0],[3,0],[3,1]]",
            "invalid",
          ]),
        ],
      ),
      "group_id",
      "hull_polygon_json",
    );

    expect([...result.frameTimesNs]).toEqual([100n]);
    expect([...result.framePolygonOffsets]).toEqual([0, 2]);
    expect([...result.polygonPointOffsets]).toEqual([0, 3, 6]);
    expect([...result.positionsXY]).toEqual([0, 0, 1, 0, 1, 1, 2, 0, 3, 0, 3, 1]);
    expect(result.objectIds).toEqual(["away", "home"]);
  });

  it("keeps influence grid timestamps and grid spacing instead of interpolating values", () => {
    const result = prepareTacticalGridWindow(
      decoded(
        [100n, 100n, 100n, 100n, 1_000n],
        [
          numbers("x_m", [0, 5, 0, 5, 0]),
          numbers("y_m", [0, 0, 4, 4, 0]),
          strings("owner_group_id", ["home", "away", "home", "away", "home"]),
          numbers("arrival_time_s", [1, 2, 3, 4, 5]),
        ],
      ),
    );

    expect([...result.gridTimesNs]).toEqual([100n, 1_000n]);
    expect([...result.gridOffsets]).toEqual([0, 4, 5]);
    expect(result.cellWidthM[0]).toBe(5);
    expect(result.cellWidthM[1]).toBeNaN();
    expect(result.cellHeightM[0]).toBe(4);
    expect(result.cellHeightM[1]).toBeNaN();
    expect([...result.values]).toEqual([1, 2, 3, 4, 5]);
  });

  it("prepares an unowned generic scalar grid without inventing a team", () => {
    const result = prepareTacticalGridWindow(
      decoded(
        [100n, 100n, 100n, 100n],
        [
          numbers("x_m", [0, 1, 0, 1]),
          numbers("y_m", [0, 0, 1, 1]),
          numbers("scalar_value", [2, 4, 3, 5]),
        ],
      ),
      "scalar_value",
      null,
    );

    expect(result.groupIds).toEqual([]);
    expect([...result.groupIndexes]).toEqual([-1, -1, -1, -1]);
    expect([...result.values]).toEqual([2, 4, 3, 5]);
  });

  it("keeps discrete event identity, type and canonical time", () => {
    const result = prepareEventWindow(
      decoded(
        [300n, 100n],
        [
          strings("event_id", ["e2", "e1"]),
          strings("event_type", ["Shot", "Pass"]),
          strings("event_subtype", ["Goal", ""]),
          numbers("x_m", [2, 1]),
          numbers("y_m", [4, 3]),
        ],
      ),
    );

    expect([...result.timeNs]).toEqual([300n, 100n]);
    expect(result.eventIds).toEqual(["e2", "e1"]);
    expect(result.eventTypes).toEqual(["Shot", "Pass"]);
    expect(result.eventSubtypes).toEqual(["Goal", null]);
    expect([...result.positionsXY]).toEqual([2, 4, 1, 3]);
  });
});
