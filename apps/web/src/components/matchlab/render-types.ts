/** Source and processor data passed between reusable MatchLab view layers. */

/** One discrete source event placed on the pitch. */
export interface PitchEvent {
  readonly eventId: string;
  readonly tRelNs: number;
  readonly type: string;
  readonly subtype: string | null;
  readonly xM: number;
  readonly yM: number;
}

export type TacticalRole = "home" | "away" | "other";

export interface TacticalHull {
  readonly groupId: string;
  readonly role: TacticalRole;
  readonly points: readonly [number, number][];
}

export interface TacticalTerritoryCell {
  readonly entityId: string;
  readonly groupId: string;
  readonly role: TacticalRole;
  readonly points: readonly [number, number][];
}

export interface TacticalInfluenceCell {
  readonly xM: number;
  readonly yM: number;
  readonly widthM: number;
  readonly heightM: number;
  readonly groupId: string;
  readonly role: TacticalRole;
  readonly arrivalTimeS: number;
}

export interface TacticalOverlay {
  readonly hulls: readonly TacticalHull[];
  readonly territoryCells: readonly TacticalTerritoryCell[];
  readonly influenceCells: readonly TacticalInfluenceCell[];
}

/** Presentation switches shared by the parity renderer and the R3F scene. */
export interface PitchLayers {
  readonly trails: boolean;
  readonly labels: boolean;
  readonly events: boolean;
  readonly geometry: boolean;
  readonly territory: boolean;
  readonly influence: boolean;
}

export const DEFAULT_PITCH_LAYERS: PitchLayers = {
  trails: true,
  labels: true,
  events: true,
  geometry: false,
  territory: false,
  influence: false,
};

export const EMPTY_TACTICAL_OVERLAY: TacticalOverlay = {
  hulls: [],
  territoryCells: [],
  influenceCells: [],
};
