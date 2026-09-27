import type { GameEditionView, GamePlayView } from "@/api/types";

export type GameSport = "nba" | "nhl" | "basketball";

export const NHL_PLAY_SOURCE_COLUMNS = [
  "event_player_1_name",
  "event_player_2_name",
  "event_player_3_name",
  "home_skaters",
  "away_skaters",
  "home_goalie",
  "away_goalie",
  ...Array.from({ length: 7 }, (_value, index) => `home_on_${index + 1}`),
  ...Array.from({ length: 7 }, (_value, index) => `away_on_${index + 1}`),
] as const;

export interface EventFact {
  readonly label: string;
  readonly value: string;
}

export interface EventPresentation {
  readonly label: string;
  readonly description: string | null;
  readonly facts: readonly EventFact[];
  readonly schemaMatchesSport: boolean;
}

export interface GameMetricColumn {
  readonly key: string;
  readonly label: string;
}

const BOX_METRICS: Record<GameSport, Record<string, readonly GameMetricColumn[]>> = {
  basketball: {},
  nba: {
    player_game: [
      { key: "source__minutes", label: "MIN" },
      { key: "source__points", label: "PTS" },
      { key: "source__rebounds", label: "REB" },
      { key: "source__assists", label: "AST" },
      { key: "source__field_goals_made", label: "FGM" },
      { key: "source__three_point_field_goals_made", label: "3PM" },
      { key: "source__blocks", label: "BLK" },
      { key: "source__plus_minus", label: "+/-" },
    ],
    team_game: [
      { key: "source__team_score", label: "PTS" },
      { key: "source__field_goal_pct", label: "FG%" },
      { key: "source__three_point_field_goal_pct", label: "3P%" },
      { key: "source__total_rebounds", label: "REB" },
      { key: "source__assists", label: "AST" },
      { key: "source__blocks", label: "BLK" },
      { key: "source__turnovers", label: "TO" },
    ],
  },
  nhl: {
    skater_game: [
      { key: "source__goals", label: "G" },
      { key: "source__assists", label: "A" },
      { key: "source__points", label: "PTS" },
      { key: "source__plus_minus", label: "+/-" },
      { key: "source__shots_on_goal", label: "SOG" },
      { key: "source__hits", label: "HIT" },
      { key: "source__blocked_shots", label: "BLK" },
      { key: "source__pim", label: "PIM" },
      { key: "source__faceoff_winning_pctg", label: "FO%" },
      { key: "source__toi", label: "TOI" },
    ],
    goalie_game: [
      { key: "source__saves", label: "SV" },
      { key: "source__shots_against", label: "SA" },
      { key: "source__save_pctg", label: "SV%" },
      { key: "source__goals_against", label: "GA" },
      { key: "source__toi", label: "TOI" },
      { key: "source__decision", label: "Decision" },
      { key: "source__starter", label: "Starter" },
    ],
    team_game: [
      { key: "source__goals", label: "G" },
      { key: "source__shots_on_goal", label: "SOG" },
      { key: "source__power_play_goals", label: "PPG" },
      { key: "source__pim", label: "PIM" },
      { key: "source__hits", label: "HIT" },
      { key: "source__blocked_shots", label: "BLK" },
      { key: "source__faceoff_win_pctg", label: "FO%" },
    ],
  },
};

export function gameSport(edition: GameEditionView): GameSport | null {
  if (edition.league_id === "nba") return "nba";
  if (edition.sport_id === "basketball") return "basketball";
  if (edition.league_id === "nhl" || edition.sport_id === "ice_hockey") return "nhl";
  return null;
}

export function sourceColumnsFor(sport: GameSport): readonly string[] {
  return sport === "nhl" ? NHL_PLAY_SOURCE_COLUMNS : [];
}

export function metricColumns(
  sport: GameSport,
  family: string,
  available: readonly string[],
): readonly GameMetricColumn[] {
  const columns = BOX_METRICS[sport][family] ?? [];
  return columns.filter((column) => available.includes(column.key));
}

export function presentEvent(sport: GameSport, play: GamePlayView): EventPresentation {
  if (sport === "basketball") {
    return {
      label: play.provider_event_type,
      description: null,
      facts: [],
      schemaMatchesSport: false,
    };
  }
  const schema =
    sport === "nba" ? "sportsdataverse.espn_nba.pbp" : "sportsdataverse.nhl.pbp_lite";
  const schemaMatchesSport = play.attributes_schema_id === schema;
  if (!schemaMatchesSport) {
    return {
      label: play.provider_event_type,
      description: null,
      facts: [],
      schemaMatchesSport: false,
    };
  }

  const attributes = play.attributes;
  if (sport === "nba") {
    return {
      label: stringValue(attributes.type_text) ?? play.provider_event_type,
      description: stringValue(attributes.text),
      facts: facts([
        ["Scoring play", booleanValue(attributes.scoring_play)],
        ["Points on play", numberValue(attributes.score_value)],
        ["Points attempted", numberValue(attributes.points_attempted)],
        ["Shooting play", booleanValue(attributes.shooting_play)],
      ]),
      schemaMatchesSport,
    };
  }

  return {
    label: stringValue(attributes.event) ?? play.provider_event_type,
    description: stringValue(attributes.description),
    facts: facts([
      ["Secondary type", stringValue(attributes.secondary_type)],
      ["Strength", stringValue(attributes.strength_state)],
      ["Penalty", stringValue(attributes.penalty_severity)],
      ["Penalty minutes", numberValue(attributes.penalty_minutes)],
      ["Shot distance", numberValue(attributes.shot_distance)],
      ["Shot angle", numberValue(attributes.shot_angle)],
      ["Expected goals", numberValue(attributes.xg)],
      ["Empty net", booleanValue(attributes.empty_net)],
    ]),
    schemaMatchesSport,
  };
}

export function clockLabel(play: GamePlayView | null): string | null {
  const clock = play?.source_clock?.clock;
  return typeof clock === "string" ? clock : null;
}

export function clockDirection(play: GamePlayView | null): string | null {
  const direction = play?.source_clock?.direction;
  if (direction === "count_down") return "count down";
  if (direction === "count_up") return "count up";
  return null;
}

export function boxValue(row: Record<string, unknown>, key: string): string | number | null {
  const value = row[key];
  if (typeof value === "string" || typeof value === "number") return value;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return null;
}

export function sourceName(row: Record<string, unknown>): string | null {
  for (const key of ["source__athlete_display_name", "source__player_name", "source__team_display_name", "source__team_name"]) {
    const value = row[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return null;
}

function facts(items: readonly (readonly [string, string | null])[]): EventFact[] {
  return items.flatMap(([label, value]) => (value === null ? [] : [{ label, value }]));
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numberValue(value: unknown): string | null {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : null;
}

function booleanValue(value: unknown): string | null {
  return typeof value === "boolean" ? (value ? "Yes" : "No") : null;
}
