/**
 * Pose view ownership: scope (one subject or all), coordinate frame and camera
 * mode as one consistent state.
 *
 * They used to be three independent `useState`s mutated from four control
 * groups, which made contradictions reachable (all-subject scope with a
 * follow-subject camera, a body-local frame with a world-fixed camera). Every
 * action here returns a state that satisfies the invariants:
 *
 * - all-subject scope uses the match/world frame (body-local recentring is per
 *   subject) and a group camera: `all_subjects`, `world_fixed` or `manual`;
 * - body-local frame uses `body_local`, `joint_focus` or `manual`;
 * - a single subject in match/world uses `follow_subject`, `joint_focus`,
 *   `world_fixed` or `manual`.
 */

import type { CameraMode, PoseCoordinateMode } from "@/components/pose/pose-model";

export type PoseScope = "subject" | "all";

export interface PoseViewState {
  readonly scope: PoseScope;
  readonly frame: PoseCoordinateMode;
  readonly camera: CameraMode;
}

export type PoseViewAction =
  | { readonly type: "scope"; readonly scope: PoseScope }
  | { readonly type: "frame"; readonly frame: PoseCoordinateMode }
  | { readonly type: "camera"; readonly camera: CameraMode }
  | { readonly type: "manual" }
  | { readonly type: "reset" };

export const INITIAL_POSE_VIEW: PoseViewState = {
  scope: "subject",
  frame: "body_local",
  camera: "body_local",
};

export function allowedCameras(state: Pick<PoseViewState, "scope" | "frame">): readonly CameraMode[] {
  if (state.scope === "all") return ["all_subjects", "world_fixed", "manual"];
  if (state.frame === "body_local") return ["body_local", "joint_focus", "manual"];
  return ["follow_subject", "joint_focus", "world_fixed", "manual"];
}

function defaultCamera(scope: PoseScope, frame: PoseCoordinateMode): CameraMode {
  if (scope === "all") return "all_subjects";
  return frame === "body_local" ? "body_local" : "follow_subject";
}

export function isConsistent(state: PoseViewState): boolean {
  if (state.scope === "all" && state.frame !== "match_world") return false;
  return allowedCameras(state).includes(state.camera);
}

export function poseViewReducer(state: PoseViewState, action: PoseViewAction): PoseViewState {
  switch (action.type) {
    case "scope": {
      if (action.scope === state.scope) return state;
      return action.scope === "all"
        ? { scope: "all", frame: "match_world", camera: "all_subjects" }
        : { scope: "subject", frame: "body_local", camera: "body_local" };
    }
    case "frame": {
      if (state.scope === "all" || action.frame === state.frame) return state;
      const keep = allowedCameras({ scope: state.scope, frame: action.frame }).includes(state.camera);
      return { scope: state.scope, frame: action.frame, camera: keep ? state.camera : defaultCamera(state.scope, action.frame) };
    }
    case "camera": {
      // A camera mode implies the scope/frame it needs, so choosing it never
      // leaves a contradictory combination behind.
      switch (action.camera) {
        case "body_local":
          return { scope: "subject", frame: "body_local", camera: "body_local" };
        case "follow_subject":
          return { scope: "subject", frame: "match_world", camera: "follow_subject" };
        case "all_subjects":
          return { scope: "all", frame: "match_world", camera: "all_subjects" };
        case "world_fixed":
          return { scope: state.scope, frame: "match_world", camera: "world_fixed" };
        case "joint_focus":
          return { scope: "subject", frame: state.scope === "all" ? "match_world" : state.frame, camera: "joint_focus" };
        case "manual":
          return { ...state, camera: "manual" };
      }
      return state;
    }
    case "manual":
      return state.camera === "manual" ? state : { ...state, camera: "manual" };
    case "reset":
      return { scope: state.scope, frame: state.scope === "all" ? "match_world" : "body_local", camera: defaultCamera(state.scope, state.scope === "all" ? "match_world" : "body_local") };
  }
}
