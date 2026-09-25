import type { Page, Route } from "@playwright/test";

/**
 * Deterministic API fixtures for e2e.
 *
 * Shapes mirror the FastAPI OpenAPI contract exactly (the same fields the
 * generated client consumes). Arrow window requests are answered with 404 so
 * the UI exercises its documented JSON fallback, keeping the suite independent
 * of binary fixtures.
 */

export const DATASET = {
  dataset_id: "skillcorner-opendata",
  name: "SkillCorner Open Data",
  provider: "SkillCorner",
  domain: "football",
  doi: null,
  upstream_urls: ["https://github.com/SkillCorner/opendata"],
  modalities: ["tracking", "pose"],
  license: {
    policy_id: "skillcorner-opendata",
    identifier: "CC BY 4.0",
    status: "declared",
    attribution_required: true,
    noncommercial_only: false,
    share_alike: false,
    redistribution: "conditional",
    local_only: false,
    restrictions: [],
    notice: "CC BY 4.0; attribution required; redistribution: conditional",
  },
  version_count: 1,
  session_count: 1,
  subject_count: 3,
  trial_count: 1,
  stream_count: 2,
  metric_count: 1,
  quality_issue_count: 1,
};

const TRACKING_STREAM = {
  stream_id: "tracking-1",
  modality: "tracking",
  measurement_class: "MODEL_ESTIMATED",
  subject_id: null,
  trial_id: "period-1",
  device_id: null,
  nominal_sampling_rate_hz: 10,
  si_units: ["m"],
  source_unit: "m",
  coordinate_frame_id: "skillcorner-pitch-m",
  pitch_dimensions_m: { length_m: 105, width_m: 68 },
  synchronization_spec_id: "skillcorner-source-provided-match-clock",
  clock_id: "skillcorner-match-clock",
  skeleton_id: null,
  sample_artifact_ids: ["tracking-sample"],
  sample_row_count: 100_000,
};

const POSE_DISPLAY_CONNECTIONS = [
  ["nose", "neck"], ["nose", "lEye"], ["nose", "rEye"],
  ["lEye", "lEar"], ["rEye", "rEar"], ["neck", "lShoulder"],
  ["neck", "rShoulder"], ["neck", "midHip"], ["lShoulder", "lElbow"],
  ["lElbow", "lWrist"], ["rShoulder", "rElbow"], ["rElbow", "rWrist"],
  ["lWrist", "lThumb"], ["lWrist", "lPinky"], ["rWrist", "rThumb"],
  ["rWrist", "rPinky"], ["midHip", "lHip"], ["midHip", "rHip"],
  ["lHip", "lKnee"], ["lKnee", "lAnkle"], ["rHip", "rKnee"],
  ["rKnee", "rAnkle"], ["lAnkle", "lHeel"], ["lAnkle", "lBigToe"],
  ["lBigToe", "lSmallToe"], ["rAnkle", "rHeel"], ["rAnkle", "rBigToe"],
  ["rBigToe", "rSmallToe"],
].map(([start_joint_name, end_joint_name]) => ({ start_joint_name, end_joint_name }));

const POSE_STREAM = {
  stream_id: "pose-1",
  modality: "pose",
  measurement_class: "MODEL_ESTIMATED",
  subject_id: null,
  trial_id: "period-1",
  device_id: null,
  nominal_sampling_rate_hz: 25,
  si_units: ["m"],
  source_unit: "m",
  coordinate_frame_id: "skillcorner-pose-hybrid-m",
  synchronization_spec_id: "skillcorner-source-provided-match-clock",
  clock_id: "skillcorner-match-clock",
  skeleton_id: "skillcorner-bodypose-29-landmarks",
  skeleton_topology: "landmark_set",
  skeleton_joint_names: [
    "nose", "neck", "lEye", "rEye", "lEar", "rEar", "lShoulder", "rShoulder",
    "lElbow", "rElbow", "lWrist", "rWrist", "lThumb", "rThumb", "lPinky", "rPinky",
    "midHip", "lHip", "rHip", "lKnee", "rKnee", "lAnkle", "rAnkle", "lHeel",
    "rHeel", "lBigToe", "rBigToe", "lSmallToe", "rSmallToe",
  ],
  skeleton_display_connections: POSE_DISPLAY_CONNECTIONS,
  sample_artifact_ids: ["pose-sample"],
  sample_row_count: 100_000,
};

export const SESSION = {
  dataset_id: "skillcorner-opendata",
  session: {
    session_id: "1925299",
    kind: "match",
    label: "Eintracht Frankfurt vs Bayern",
    started_at: null,
    ended_at: null,
    participant_count: 3,
    trial_count: 1,
    stream_count: 2,
  },
  participants: [
    { subject_id: "SC-P1", role: "player", group_label: "home" },
    { subject_id: "SC-P2", role: "player", group_label: "away" },
    { subject_id: "560986", role: "player", group_label: "away" },
  ],
  trials: [
    {
      trial_id: "period-1",
      subject_id: null,
      parent_trial_id: null,
      label: "first half",
      started_at: null,
      ended_at: null,
    },
  ],
  streams: [TRACKING_STREAM, POSE_STREAM],
};

const TRACKING_ARTIFACT = {
  artifact_id: "tracking-sample",
  dataset_id: "skillcorner-opendata",
  stream_id: "tracking-1",
  layer: "silver",
  relative_path: "silver/dataset_id=skillcorner-opendata/tracking/sample.parquet",
  format: "parquet",
  compression: "zstd",
  checksum_sha256: "a".repeat(64),
  row_count: 100_000,
  byte_size: 4096,
  artifact_kind: "sample",
  modality: "tracking",
  measurement_class: "MODEL_ESTIMATED",
  si_units: ["m"],
  coordinate_frame_id: "skillcorner-pitch-m",
  synchronization_spec_id: "skillcorner-source-provided-match-clock",
  canonical_time_min_ns: 0,
  canonical_time_max_ns: 20_000_000_000,
  entity_column: "object_id",
  entity_count: 2,
  entity_ids: ["p1", "p2"],
};

const POSE_ARTIFACT = {
  ...TRACKING_ARTIFACT,
  artifact_id: "pose-sample",
  stream_id: "pose-1",
  relative_path: "silver/dataset_id=skillcorner-opendata/pose/sample.parquet",
  coordinate_frame_id: "skillcorner-pose-hybrid-m",
  artifact_kind: "sample",
  modality: "pose",
  row_count: 100_000,
  byte_size: 8192,
  entity_column: "subject_id",
  entity_count: 3,
  entity_ids: ["SC-P1", "SC-P2", "560986"],
};

const TRACKING_TIMES = [0, 40_000_000, 2_000_000_000, 4_000_000_000, 6_000_000_000, 8_000_000_000, 10_000_000_000, 12_000_000_000, 14_000_000_000, 16_000_000_000, 18_000_000_000, 20_000_000_000] as const;
const TRACKING_WINDOW_ROWS = TRACKING_TIMES.flatMap((t_rel_ns, index) => [
  { t_rel_ns, object_id: "p1", object_type: "player", group_id: "home", x_m: -5 + index * 0.2, y_m: 2 + index * 0.1, is_detected: true },
  { t_rel_ns, object_id: "p2", object_type: "player", group_id: "away", x_m: 5 - index * 0.2, y_m: -2 - index * 0.1, is_detected: index % 3 !== 0 },
  { t_rel_ns, object_id: "ball", object_type: "ball", group_id: null, x_m: 0.2 + index * 0.05, y_m: 0.1, is_detected: true },
]);

const TRACKING_WINDOW = {
  meta: {
    artifact: TRACKING_ARTIFACT,
    from_ns: 0,
    to_ns: 20_000_000_000,
    columns: ["t_rel_ns", "object_id", "object_type", "group_id", "x_m", "y_m", "is_detected"],
    source_rows: TRACKING_WINDOW_ROWS.length,
    returned_rows: TRACKING_WINDOW_ROWS.length,
    canonical_time_min_ns: 0,
    canonical_time_max_ns: 20_000_000_000,
    reduction: null,
    units: { x_m: "m", y_m: "m" },
    coordinate_frame_id: "skillcorner-pitch-m",
    measurement_class: "MODEL_ESTIMATED",
    display_note: "Exact.",
  },
  rows: TRACKING_WINDOW_ROWS,
};

const POSE_LANDMARKS = [
  "nose", "neck", "lEye", "rEye", "lEar", "rEar", "lShoulder", "rShoulder",
  "lElbow", "rElbow", "lWrist", "rWrist", "lThumb", "rThumb", "lPinky", "rPinky",
  "midHip", "lHip", "rHip", "lKnee", "rKnee", "lAnkle", "rAnkle", "lHeel",
  "rHeel", "lBigToe", "rBigToe", "lSmallToe", "rSmallToe",
] as const;

const POSE_LANDMARK_COORDINATES: Record<string, [number, number, number]> = {
  nose: [0, 0, 0.9],
  neck: [0, 0, 0.55],
  lEye: [-0.06, -0.01, 0.94],
  rEye: [0.06, -0.01, 0.94],
  lEar: [-0.12, 0, 0.88],
  rEar: [0.12, 0, 0.88],
  lShoulder: [-0.25, 0, 0.5],
  rShoulder: [0.25, 0, 0.5],
  lElbow: [-0.45, 0, 0.18],
  rElbow: [0.45, 0, 0.18],
  lWrist: [-0.58, 0, -0.12],
  rWrist: [0.58, 0, -0.12],
  lThumb: [-0.66, -0.03, -0.2],
  rThumb: [0.66, -0.03, -0.2],
  lPinky: [-0.66, 0.04, -0.16],
  rPinky: [0.66, 0.04, -0.16],
  midHip: [0, 0, -0.35],
  lHip: [-0.18, 0, -0.4],
  rHip: [0.18, 0, -0.4],
  lKnee: [-0.2, 0.01, -0.85],
  rKnee: [0.2, 0.01, -0.85],
  lAnkle: [-0.18, 0.02, -1.25],
  rAnkle: [0.18, 0.02, -1.25],
  lHeel: [-0.18, -0.08, -1.3],
  rHeel: [0.18, -0.08, -1.3],
  lBigToe: [-0.18, 0.12, -1.3],
  rBigToe: [0.18, 0.12, -1.3],
  lSmallToe: [-0.28, 0.12, -1.3],
  rSmallToe: [0.28, 0.12, -1.3],
};

const POSE_ROWS = POSE_LANDMARKS.map((joint_name) => {
  const coordinates = POSE_LANDMARK_COORDINATES[joint_name] ?? [0, 0, 0];
  return {
    t_rel_ns: 0,
    subject_id: "SC-P1",
    joint_name,
    is_available: true,
    x_m: coordinates[0],
    y_m: coordinates[1],
    z_m: coordinates[2],
    error_m: joint_name === "lKnee" ? 0.04 : joint_name === "lAnkle" ? 0.05 : 0.03,
  };
});
const POSE_TIMES_P1 = [0, 40_000_000, 4_000_000_000, 8_000_000_000, 12_000_000_000, 16_000_000_000, 20_000_000_000] as const;
const POSE_TIMES_P2 = [12_000_000_000, 16_000_000_000, 20_000_000_000] as const;
const POSE_ROWS_P2 = POSE_ROWS.map((row) => ({
  ...row,
  subject_id: "SC-P2",
  x_m: row.x_m + 3,
  y_m: row.y_m - 2,
}));
const poseRowsAt = (rows: typeof POSE_ROWS, times: readonly number[], subjectOffset: number) =>
  times.flatMap((t_rel_ns, index) => rows.map((row) => ({
    ...row,
    t_rel_ns,
    x_m: row.x_m + index * 0.12 + subjectOffset,
    z_m: row.z_m + (row.joint_name === "lKnee" ? index * 0.04 : 0),
  })));
const POSE_WINDOW_ROWS = [
  ...poseRowsAt(POSE_ROWS, POSE_TIMES_P1, 0),
  ...poseRowsAt(POSE_ROWS_P2, POSE_TIMES_P2, 0),
];

function poseObservationsInRange(fromNs: number, toNs: number) {
  const timesBySubject = new Map<string, Set<number>>();
  for (const row of POSE_WINDOW_ROWS) {
    if (
      row.t_rel_ns < fromNs ||
      row.t_rel_ns > toNs ||
      row.is_available !== true ||
      typeof row.x_m !== "number" ||
      typeof row.y_m !== "number" ||
      typeof row.z_m !== "number"
    ) continue;
    const times = timesBySubject.get(row.subject_id) ?? new Set<number>();
    times.add(row.t_rel_ns);
    timesBySubject.set(row.subject_id, times);
  }
  return [...timesBySubject.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([entity_id, times]) => {
    const ordered = [...times].sort((left, right) => left - right);
    return {
      entity_id,
      first_observed_ns: ordered[0]!,
      last_observed_ns: ordered.at(-1)!,
      observation_count: ordered.length,
    };
  });
}

const POSE_WINDOW = {
  meta: {
    artifact: POSE_ARTIFACT,
    from_ns: 0,
    to_ns: 20_000_000_000,
    columns: [
      "t_rel_ns",
      "subject_id",
      "joint_name",
      "is_available",
      "x_m",
      "y_m",
      "z_m",
      "error_m",
    ],
    source_rows: POSE_WINDOW_ROWS.length,
    returned_rows: POSE_WINDOW_ROWS.length,
    canonical_time_min_ns: 0,
    canonical_time_max_ns: 20_000_000_000,
    reduction: null,
    units: { x_m: "m", y_m: "m", z_m: "m", error_m: "m" },
    coordinate_frame_id: "skillcorner-pose-hybrid-m",
    measurement_class: "MODEL_ESTIMATED",
    display_note: "Exact.",
  },
  rows: POSE_WINDOW_ROWS,
};

export const METRIC = {
  derived_metric_id: "dm-pose-rom",
  dataset_id: "skillcorner-opendata",
  metric_id: "pose.angular_rom.left_knee",
  metric_name: "Range of motion for angle left_knee",
  metric_description: "max - min of the observed angle.",
  si_unit: "rad",
  measurement_class: "PIPELINE_DERIVED",
  value_kind: "scalar",
  value_num: 2.7,
  value_json: null,
  subject_id: "SC-P1",
  session_id: "1925299",
  trial_id: "period-1",
  stream_id: "pose-1",
  entity_id: "SC-P1",
  algorithm_id: "pose.translation_invariant_kinematics",
  algorithm_version: "1.0.0",
  parameters_hash: "e".repeat(64),
  code_git_sha: "b".repeat(40),
  run_id: "run-pose",
  computed_at: "2026-09-18T12:00:00+00:00",
  provenance: { gap_policy: { strategy: "contiguous_segments" } },
};

const METRIC_DEFINITIONS = [
  {
    metric_id: METRIC.metric_id,
    name: METRIC.metric_name,
    si_unit: METRIC.si_unit,
    measurement_class: METRIC.measurement_class,
    value_kind: METRIC.value_kind,
    description: METRIC.metric_description,
    algorithm_id: METRIC.algorithm_id,
    dataset_ids: [DATASET.dataset_id],
    value_count: 1,
  },
];

export const PROVENANCE = {
  derived_metric_id: "dm-pose-rom",
  nodes: [
    { id: "dataset:skillcorner-opendata", kind: "dataset", label: "SkillCorner Open Data", status: null, measurement_class: null, details: { dataset_id: "skillcorner-opendata" } },
    { id: "artifact:pose-sample", kind: "silver_artifact", label: "pose-sample", status: null, measurement_class: "MODEL_ESTIMATED", details: { relative_path: "silver/...", checksum_sha256: "a".repeat(64) } },
    { id: "stream:pose-1", kind: "sensor_stream", label: "pose-1", status: null, measurement_class: "MODEL_ESTIMATED", details: { modality: "pose" } },
    { id: "algorithm:pose.translation_invariant_kinematics", kind: "algorithm", label: "Translation-invariant pose kinematics@1.0.0", status: null, measurement_class: null, details: { code_git_sha: "b".repeat(40) } },
    { id: "run:run-pose", kind: "processing_run", label: "run-pose", status: "completed", measurement_class: null, details: { code_git_sha: "b".repeat(40) } },
    { id: "derived:dm-pose-rom", kind: "derived_metric", label: "dm-pose-rom", status: null, measurement_class: "PIPELINE_DERIVED", details: { value_num: 2.7, si_unit: "rad" } },
    { id: "gold:dm-pose-rom", kind: "gold_row", label: "gold_trial_metrics · dm-pose-rom", status: null, measurement_class: "PIPELINE_DERIVED", details: { mart: "gold_trial_metrics" } },
  ],
  edges: [
    { id: "e1", source: "dataset:skillcorner-opendata", target: "artifact:pose-sample", label: "input artifact" },
    { id: "e2", source: "artifact:pose-sample", target: "stream:pose-1", label: "canonicalizes to" },
    { id: "e3", source: "stream:pose-1", target: "algorithm:pose.translation_invariant_kinematics", label: "computed by" },
    { id: "e4", source: "algorithm:pose.translation_invariant_kinematics", target: "run:run-pose", label: "executed as" },
    { id: "e5", source: "run:run-pose", target: "derived:dm-pose-rom", label: "results in" },
    { id: "e6", source: "derived:dm-pose-rom", target: "gold:dm-pose-rom", label: "served as" },
  ],
  provenance: { algorithm_id: "pose.translation_invariant_kinematics", code_git_sha: "b".repeat(40) },
  lineage_note: "Selected result lineage only. Scientific values are never recomputed from the graph.",
};

export const METHODOLOGY = {
  metric: {
    metric_id: "pose.angular_rom.left_knee",
    name: "Range of motion for angle left_knee",
    si_unit: "rad",
    measurement_class: "PIPELINE_DERIVED",
    value_kind: "scalar",
    description: "max - min of the observed angle.",
    algorithm_id: "pose.translation_invariant_kinematics",
  },
  algorithm: {
    algorithm_id: "pose.translation_invariant_kinematics",
    name: "Translation-invariant pose kinematics",
    version: "1.0.0",
    kind: "processor",
    code_git_sha: "b".repeat(40),
    parameters_hash: "e".repeat(64),
    parameters: {
      gap_policy: { strategy: "contiguous_segments", max_gap_factor: 1.5 },
      segments: [{ name: "left_thigh", start_landmark: "lHip", end_landmark: "lKnee" }],
      angles: [
        {
          name: "left_knee",
          vertex_landmark: "lKnee",
          first_landmark: "lHip",
          second_landmark: "lAnkle",
        },
      ],
    },
    description: "Relative vectors and explicit angles.",
    citation: null,
  },
  measurement_class_semantics: "Computed by a versioned DynamisData processor from canonical inputs.",
  measurement_class_never_means: [
    "SOURCE_DERIVED is not ground truth.",
    "MODEL_ESTIMATED is not a measurement.",
  ],
  provenance_fields: ["measurement_class", "run_id", "code Git SHA"],
};

const QUALITY = {
  total: 1,
  limit: 200,
  offset: 0,
  rows: [
    {
      issue_id: "issue-1",
      dataset_id: "skillcorner-opendata",
      run_id: null,
      session_id: "1925299",
      stream_id: "tracking-1",
      subject_id: null,
      trial_id: null,
      sample_index: 12,
      rule: "tracking.ball_gap",
      severity: "WARNING",
      state: "VALID",
      evidence: { gap_frames: 3 },
      detected_at: "2026-09-18T12:00:00+00:00",
    },
  ],
};

const RIGHTS = {
  policies: [
    {
      license: DATASET.license,
      dataset_ids: ["skillcorner-opendata"],
    },
  ],
};

const STATUS = {
  database: "ok",
  db_schema: "dynamis",
  gold_schema: "gold",
  gold_published: true,
  dataset_count: 1,
  metric_count: 1,
  run_count: 1,
  quality_issue_count: 1,
};

const TACTICAL_CAPABILITY = {
  dataset_id: "skillcorner-opendata",
  accepted_slice: { match_id: "1925299" },
  semantics: {
    team_identity: "metadata team_id joined to tracking player_id",
    attacking_direction: "unavailable",
    event_semantics: "unavailable",
    measurement_classes: { tracking: "MODEL_ESTIMATED" },
  },
  capabilities: {
    level_a_geometry: "supported_with_model_input_quality",
    level_b_territory: "supported_with_model_input_quality",
    level_c_influence: "supported_partial_with_model_input_quality",
    level_d_event_linked: "unavailable",
    level_e_shape_phase: "unavailable",
    matchlab_v3_functional_units: "supported_from_declared_roles",
  },
  quality_evidence: { tracking_rate_hz: 10, local_event_files: false, local_phase_files: false },
  unavailable_reasons: ["no accepted local event or phase artifact"],
};

const RUNS = {
  total: 1,
  limit: 200,
  offset: 0,
  rows: [
    {
      run_id: "run-pose",
      dataset_id: "skillcorner-opendata",
      algorithm_id: "pose.translation_invariant_kinematics",
      algorithm_name: "Translation-invariant pose kinematics",
      algorithm_version: "1.0.0",
      kind: "processor",
      status: "completed",
      code_git_sha: "b".repeat(40),
      parameters_hash: "e".repeat(64),
      started_at: null,
      completed_at: null,
      input_checksums: ["c".repeat(64)],
      metric_count: 1,
      artifact_count: 1,
      notes: null,
    },
  ],
};

function body(pathname: string): unknown | undefined {
  if (pathname === "/api/serving/status") return STATUS;
  if (pathname === "/api/catalog/datasets") return [DATASET];
  if (pathname === "/api/catalog/datasets/skillcorner-opendata") {
    return { ...DATASET, versions: [], v1_role: "reference", initial_scope: "match 1925299", adapter_id: "skillcorner_adapter" };
  }
  if (pathname === "/api/catalog/datasets/skillcorner-opendata/sessions") return [SESSION.session];
  if (pathname === "/api/catalog/datasets/skillcorner-opendata/sessions/1925299") return SESSION;
  if (pathname === "/api/metrics") return { source: "gold", total: 1, limit: 250, offset: 0, rows: [METRIC] };
  if (pathname === "/api/metrics/definitions") return METRIC_DEFINITIONS;
  if (pathname.startsWith("/api/metrics/methodology/")) return METHODOLOGY;
  if (pathname === `/api/derived-metrics/${METRIC.derived_metric_id}/provenance`) return PROVENANCE;
  if (pathname === "/api/quality") return QUALITY;
  if (pathname === "/api/rights") return RIGHTS;
  if (pathname === "/api/runs") return RUNS;
  if (pathname === "/api/tactical/capabilities/skillcorner-opendata") return TACTICAL_CAPABILITY;
  if (pathname === "/api/tactical/quality/skillcorner-opendata") {
    return {
      dataset_id: "skillcorner-opendata",
      capabilities: TACTICAL_CAPABILITY.capabilities,
      quality_evidence: TACTICAL_CAPABILITY.quality_evidence,
      measurement_classes: TACTICAL_CAPABILITY.semantics.measurement_classes,
      unavailable_reasons: TACTICAL_CAPABILITY.unavailable_reasons,
      disclosure: "PIPELINE_DERIVED is deterministic output; MODEL_ESTIMATED is assumption-bearing.",
    };
  }
  if (pathname === "/api/tactical/methodology") return { metrics: [], authority: "RES-110" };
  if (pathname === "/api/tactical/artifacts") return [];
  if (pathname === "/api/processing/artifacts") return [];
  if (pathname === "/api/artifacts/tracking-sample") return TRACKING_ARTIFACT;
  if (pathname === "/api/artifacts/pose-sample") {
    return { ...POSE_ARTIFACT, entity_observations: poseObservationsInRange(Number.NEGATIVE_INFINITY, Number.POSITIVE_INFINITY) };
  }
  if (pathname === "/api/artifacts/tracking-sample/window") return TRACKING_WINDOW;
  if (pathname === "/api/artifacts/pose-sample/window") return POSE_WINDOW;
  return undefined;
}

function windowPayload(url: URL): unknown | undefined {
  const payload = body(url.pathname);
  if (typeof payload !== "object" || payload === null || !Array.isArray((payload as { rows?: unknown }).rows)) {
    return payload;
  }
  const fromNs = url.searchParams.has("from_ns") ? Number(url.searchParams.get("from_ns")) : Number.NEGATIVE_INFINITY;
  const toNs = url.searchParams.has("to_ns") ? Number(url.searchParams.get("to_ns")) : Number.POSITIVE_INFINITY;
  const entityId = url.searchParams.get("entity_id");
  const rows = ((payload as { rows: Array<Record<string, unknown>> }).rows).filter((row) => {
    const time = row.t_rel_ns;
    const rowEntity = row.subject_id ?? row.object_id;
    return typeof time === "number" && time >= fromNs && time <= toNs &&
      (entityId === null || String(rowEntity) === entityId);
  });
  const source = payload as { meta: Record<string, unknown>; rows: Array<Record<string, unknown>> };
  return {
    ...source,
    meta: {
      ...source.meta,
      from_ns: Number.isFinite(fromNs) ? fromNs : source.meta.from_ns,
      to_ns: Number.isFinite(toNs) ? toNs : source.meta.to_ns,
      source_rows: rows.length,
      returned_rows: rows.length,
    },
    rows,
  };
}

async function handler(route: Route): Promise<void> {
  const url = new URL(route.request().url());
  if (url.pathname.endsWith("/observations")) {
    const fromNs = url.searchParams.has("from_ns") ? Number(url.searchParams.get("from_ns")) : Number.NEGATIVE_INFINITY;
    const toNs = url.searchParams.has("to_ns") ? Number(url.searchParams.get("to_ns")) : Number.POSITIVE_INFINITY;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(poseObservationsInRange(fromNs, toNs)),
    });
    return;
  }
  if (url.pathname.endsWith("/window") && url.searchParams.get("format") === "arrow") {
    const payload = windowPayload(url);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
    return;
  }
  const payload = url.pathname.endsWith("/window") ? windowPayload(url) : body(url.pathname);
  if (payload === undefined) {
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: `unhandled ${url.pathname}` }) });
    return;
  }
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    headers: { "X-Dynamis-Fixture": "e2e" },
    body: JSON.stringify(payload),
  });
}

export async function installApiMocks(page: Page): Promise<void> {
  // Match the API namespace only: a glob like `**/api/**` would also intercept
  // application modules whose path contains `/api/` (for example
  // `src/lib/api/client.ts`).
  await page.route((url) => url.pathname.startsWith("/api/"), handler);
}
