import { describe, expect, it } from "vitest";

import {
  indexTacticalRows,
  latestRowsAtOrBefore,
  tacticalOverlayAt,
} from "@/components/pitch/tactical-overlay";
import { teamRole } from "@/components/pitch/pitch-model";

const TEAMS = ["DFL-CLU-000005", "DFL-CLU-00000P"];
const roleOf = (groupId: string) => teamRole(groupId, TEAMS);

const geometry = indexTacticalRows([
  { t_rel_ns: 0, group_id: "DFL-CLU-000005", hull_polygon_json: "[[0,0],[1,0],[0,1]]" },
  { t_rel_ns: 0, group_id: "DFL-CLU-00000P", hull_polygon_json: "[[2,0],[3,0],[2,1]]" },
  { t_rel_ns: 40, group_id: "DFL-CLU-000005", hull_polygon_json: "[[10,0],[11,0],[10,1]]" },
  { t_rel_ns: 40, group_id: "DFL-CLU-00000P", hull_polygon_json: "[[12,0],[13,0],[12,1]]" },
]);
const influence = indexTacticalRows([
  { t_rel_ns: 0, x_m: 0, y_m: 0, owner_group_id: "DFL-CLU-000005", arrival_time_s: 0.5 },
  { t_rel_ns: 0, x_m: 5, y_m: 0, owner_group_id: "DFL-CLU-00000P", arrival_time_s: 0.7 },
]);
const empty = indexTacticalRows([]);

describe("tacticalOverlayAt (RES-112 F-04/F-05)", () => {
  it("draws only the exact drawn frame", () => {
    const { overlay } = tacticalOverlayAt({ geometry, territory: empty, influence: empty }, 40, roleOf, 1_500);
    expect(overlay.hulls.map((hull) => hull.points[0]?.[0])).toEqual([10, 12]);
  });

  it("draws nothing for a frame the series does not hold rather than a neighbour", () => {
    const { overlay } = tacticalOverlayAt({ geometry, territory: empty, influence: empty }, 20, roleOf, 1_500);
    expect(overlay.hulls).toEqual([]);
    expect(tacticalOverlayAt({ geometry, territory: empty, influence: empty }, null, roleOf, 1_500).overlay.hulls).toEqual([]);
  });

  it("colours overlay items with the same team role as the entity markers", () => {
    const { overlay } = tacticalOverlayAt({ geometry, territory: empty, influence: empty }, 0, roleOf, 1_500);
    expect(overlay.hulls.map((hull) => [hull.groupId, hull.role])).toEqual([
      ["DFL-CLU-000005", "home"],
      ["DFL-CLU-00000P", "away"],
    ]);
  });

  it("uses the latest sampled influence grid within its maximum age and states its time", () => {
    const current = tacticalOverlayAt({ geometry: empty, territory: empty, influence }, 1_000, roleOf, 1_500);
    expect(current.influenceGridTimeNs).toBe(0);
    expect(current.overlay.influenceCells).toHaveLength(2);
    expect(current.overlay.influenceCells[0]?.widthM).toBe(5);
    const stale = tacticalOverlayAt({ geometry: empty, territory: empty, influence }, 2_000, roleOf, 1_500);
    expect(stale.influenceGridTimeNs).toBeNull();
    expect(stale.overlay.influenceCells).toEqual([]);
  });

  it("never uses a future grid", () => {
    expect(latestRowsAtOrBefore(indexTacticalRows([{ t_rel_ns: 10 }]), 5, 1_000)).toBeNull();
  });
});
