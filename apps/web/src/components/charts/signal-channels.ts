/**
 * Signal channel model.
 *
 * A canonical window carries every measure the source records: a force plate
 * artifact holds three force components, three moments, three centre-of-pressure
 * coordinates and a body-weight ratio. Plotting all of them on one value axis
 * makes the flagship trace unreadable — a ratio around 1 and a moment in newton
 * metres cannot share a scale.
 *
 * Channels are therefore grouped by the physical quantity they measure, each
 * group gets its own axis, and a deterministic default selects the group a
 * reader of that modality expects to see first. Labels come from the canonical
 * column vocabulary this project defines, so naming them is description rather
 * than interpretation.
 */

export interface SignalChannel {
  /** Canonical column name; the exact machine identity. */
  readonly id: string;
  readonly label: string;
  readonly unit: string;
  readonly groupId: string;
  readonly groupLabel: string;
}

export interface ChannelGroup {
  readonly id: string;
  readonly label: string;
  readonly unit: string;
  readonly channels: readonly SignalChannel[];
}

interface GroupSpec {
  readonly id: string;
  readonly label: string;
  /** Column prefixes that belong to this group. */
  readonly prefixes: readonly string[];
}

/**
 * Canonical measure groups, in the order a reader of that modality expects
 * them. The first group that a window can fill becomes the default view.
 */
const GROUPS: readonly GroupSpec[] = [
  { id: "force", label: "Ground reaction force", prefixes: ["force_x_", "force_y_", "force_z_n"] },
  {
    id: "body_weight_ratio",
    label: "Vertical force / body weight",
    prefixes: ["force_z_body_weight_ratio"],
  },
  { id: "moment", label: "Free moment", prefixes: ["moment_"] },
  { id: "cop", label: "Centre of pressure", prefixes: ["cop_"] },
  { id: "accel", label: "Acceleration", prefixes: ["accel_"] },
  { id: "gyro", label: "Angular rate", prefixes: ["gyro_"] },
  { id: "mag", label: "Magnetic field", prefixes: ["mag_"] },
  { id: "temperature", label: "Temperature", prefixes: ["temperature_"] },
  { id: "speed", label: "Speed over ground", prefixes: ["speed_"] },
  { id: "course", label: "Course over ground", prefixes: ["course_"] },
  { id: "height", label: "Ellipsoidal height", prefixes: ["ellipsoidal_height_"] },
  { id: "geodetic", label: "Geodetic position", prefixes: ["latitude_", "longitude_"] },
  { id: "ecef", label: "ECEF position", prefixes: ["ecef_"] },
  {
    id: "gnss_quality",
    label: "GNSS quality",
    prefixes: ["horizontal_accuracy_", "vertical_accuracy_", "hdop", "satellites_used"],
  },
  { id: "velocity", label: "Velocity", prefixes: ["vx_", "vy_", "vz_", "v_"] },
  { id: "position", label: "Position", prefixes: ["x_m", "y_m", "z_m"] },
];

/** Exact labels for canonical columns whose meaning a generic rule would blur. */
const LABELS: Readonly<Record<string, string>> = {
  force_x_n: "Force X",
  force_y_n: "Force Y",
  force_z_n: "Force Z (vertical)",
  force_z_body_weight_ratio: "Vertical force / body weight",
  moment_x_n_m: "Moment X",
  moment_y_n_m: "Moment Y",
  moment_z_n_m: "Moment Z",
  cop_x_m: "Centre of pressure X",
  cop_y_m: "Centre of pressure Y",
  cop_z_m: "Centre of pressure Z",
  accel_x_m_s2: "Acceleration X",
  accel_y_m_s2: "Acceleration Y",
  accel_z_m_s2: "Acceleration Z",
  gyro_x_rad_s: "Angular rate X",
  gyro_y_rad_s: "Angular rate Y",
  gyro_z_rad_s: "Angular rate Z",
  mag_x_ut: "Magnetic field X",
  mag_y_ut: "Magnetic field Y",
  mag_z_ut: "Magnetic field Z",
  temperature_deg_c: "Temperature",
  speed_m_s: "Speed over ground",
  course_deg: "Course over ground",
  ellipsoidal_height_m: "Ellipsoidal height",
  latitude_deg: "Latitude",
  longitude_deg: "Longitude",
  horizontal_accuracy_m: "Horizontal accuracy",
  vertical_accuracy_m: "Vertical accuracy",
  hdop: "HDOP",
  satellites_used: "Satellites used",
};

/**
 * The group a reader of each modality expects first. Force plates lead with
 * the vertical trace, inertial units with acceleration, GNSS with speed.
 */
const PREFERRED_GROUP: Readonly<Record<string, readonly string[]>> = {
  force: ["force", "body_weight_ratio"],
  imu: ["accel", "gyro"],
  gnss: ["speed", "velocity"],
  lpt: ["velocity", "position"],
  tracking: ["velocity", "position"],
};

/** Strip the trailing unit token a canonical column name carries. */
function humanize(column: string): string {
  const explicit = LABELS[column];
  if (explicit !== undefined) return explicit;
  const words = column.split("_").filter(Boolean);
  const head = words[0] ?? column;
  return head.charAt(0).toUpperCase() + head.slice(1) + (words.length > 1 ? ` ${words.slice(1).join(" ")}` : "");
}

function groupFor(column: string): GroupSpec | null {
  for (const group of GROUPS) {
    if (group.prefixes.some((prefix) => column.startsWith(prefix))) return group;
  }
  return null;
}

/**
 * Group a window's measure columns.
 *
 * Columns the vocabulary does not recognise still get a group of their own, so
 * a new canonical measure appears rather than silently disappearing from the
 * laboratory.
 */
export function groupChannels(
  columns: readonly string[],
  units: Readonly<Record<string, string>>,
): ChannelGroup[] {
  const byGroup = new Map<string, { label: string; channels: SignalChannel[] }>();
  for (const column of columns) {
    const spec = groupFor(column);
    const groupId = spec?.id ?? column;
    const groupLabel = spec?.label ?? humanize(column);
    const unit = units[column] ?? "1";
    const entry = byGroup.get(groupId) ?? { label: groupLabel, channels: [] };
    entry.channels.push({
      id: column,
      label: humanize(column),
      unit,
      groupId,
      groupLabel,
    });
    byGroup.set(groupId, entry);
  }

  const order = new Map(GROUPS.map((group, index) => [group.id, index]));
  return [...byGroup.entries()]
    .map(([id, entry]) => ({
      id,
      label: entry.label,
      // A group shares one axis, so it is labelled with the unit its channels
      // agree on; a disagreement falls back to dimensionless rather than
      // asserting a unit the data does not support.
      unit: entry.channels.every((channel) => channel.unit === entry.channels[0]?.unit)
        ? (entry.channels[0]?.unit ?? "1")
        : "1",
      channels: entry.channels,
    }))
    .sort((left, right) => {
      const leftOrder = order.get(left.id) ?? GROUPS.length;
      const rightOrder = order.get(right.id) ?? GROUPS.length;
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
      return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
    });
}

/**
 * The group a session opens on: the modality's preferred group when the window
 * actually contains it, otherwise the first group present. Never empty when
 * any measure exists.
 */
export function defaultGroupId(
  groups: readonly ChannelGroup[],
  modality: string,
): string | null {
  if (groups.length === 0) return null;
  for (const candidate of PREFERRED_GROUP[modality] ?? []) {
    if (groups.some((group) => group.id === candidate)) return candidate;
  }
  return groups[0]?.id ?? null;
}
