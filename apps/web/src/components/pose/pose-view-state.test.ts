import { describe, expect, it } from "vitest";

import { CAMERA_MODES, type CameraMode, type PoseCoordinateMode } from "@/components/pose/pose-model";
import {
  INITIAL_POSE_VIEW,
  isConsistent,
  poseViewReducer,
  type PoseScope,
  type PoseViewAction,
  type PoseViewState,
} from "@/components/pose/pose-view-state";

const ACTIONS: PoseViewAction[] = [
  { type: "scope", scope: "subject" },
  { type: "scope", scope: "all" },
  { type: "frame", frame: "body_local" },
  { type: "frame", frame: "match_world" },
  ...CAMERA_MODES.map((camera): PoseViewAction => ({ type: "camera", camera })),
  { type: "manual" },
  { type: "reset" },
];

describe("poseViewReducer (RES-112 P-03)", () => {
  it("never reaches a contradictory scope/frame/camera combination", () => {
    const scopes: PoseScope[] = ["subject", "all"];
    const frames: PoseCoordinateMode[] = ["body_local", "match_world"];
    const reachable: PoseViewState[] = [];
    for (const scope of scopes) {
      for (const frame of frames) {
        for (const camera of CAMERA_MODES as readonly CameraMode[]) {
          const state = { scope, frame, camera };
          if (isConsistent(state)) reachable.push(state);
        }
      }
    }
    for (const state of [INITIAL_POSE_VIEW, ...reachable]) {
      for (const action of ACTIONS) {
        const next = poseViewReducer(state, action);
        expect(isConsistent(next), `${JSON.stringify(state)} + ${JSON.stringify(action)} -> ${JSON.stringify(next)}`).toBe(true);
      }
    }
  });

  it("all-subject scope forces the world frame and a group camera", () => {
    const all = poseViewReducer(INITIAL_POSE_VIEW, { type: "scope", scope: "all" });
    expect(all).toEqual({ scope: "all", frame: "match_world", camera: "all_subjects" });
    expect(poseViewReducer(all, { type: "frame", frame: "body_local" })).toBe(all);
    expect(poseViewReducer(all, { type: "camera", camera: "follow_subject" })).toEqual({
      scope: "subject",
      frame: "match_world",
      camera: "follow_subject",
    });
  });

  it("manual ownership is kept until the reader resets", () => {
    const world = poseViewReducer(INITIAL_POSE_VIEW, { type: "frame", frame: "match_world" });
    const manual = poseViewReducer(world, { type: "manual" });
    expect(manual.camera).toBe("manual");
    expect(poseViewReducer(manual, { type: "reset" })).toEqual(INITIAL_POSE_VIEW);
  });
});
