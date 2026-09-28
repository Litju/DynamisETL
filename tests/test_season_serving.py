"""SeasonLab serving: metric registry, explicit denominators and the HTTP surface.

The HTTP tests run the real ``PostgresServingBackend`` season assembly over a small
synthetic PLAYER_SEASON Parquet file; only the two control-plane lookups (edition
registry and artifact reference) are replaced, so no PostgreSQL is required.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from dynamis.config import Settings
from dynamis.serving import season
from dynamis.serving.app import PostgresServingBackend, create_app
from dynamis.serving.models import (
    ArtifactRefView,
    LicenseView,
    SeasonEditionView,
    SeasonFamilyRef,
)

EDITION = "edition-test"
RELATIVE = "silver/season/aggregate_family=physical.parquet"


def test_basketball_efficiency_units_match_their_denominators() -> None:
    assert season._basketball_spec("picks", "handler_ppp").unit == "points per pick"
    assert season._basketball_spec("picks", "handler_ppp_at_middle").unit == "points per pick"
    assert season._basketball_spec("drives", "points_per_drive").unit == "points per drive"
    assert (
        season._basketball_spec("drives", "points_per_shot_in_drive").unit == "points per attempt"
    )


def _physical_table() -> pa.Table:
    rows = [
        # subject, name, team, team name, position, matches, distance, tip, otip, psv99
        ("sc/1", "Ana Alpha", "team-a", "Alpha FC", "Center Forward", 20, 10_000.0, 300, 250, 29.0),
        ("sc/2", "Ben Beta", "team-a", "Alpha FC", "Center Forward", 3, 9_000.0, 200, 260, 30.5),
        ("sc/2", "Ben Beta", "team-a", "Alpha FC", "Wide Attacker", 9, 9_500.0, 220, 240, 30.1),
        ("sc/3", "Cy Gamma", "team-b", "Beta FC", "Center Forward", 12, 11_000.0, 310, 290, None),
        ("sc/4", "Di Delta", "team-b", "Beta FC", "Midfield", 15, 11_500.0, 280, 330, 27.2),
    ]
    columns = list(zip(*rows, strict=True))
    return pa.table(
        {
            "subject_id": pa.array(columns[0], pa.string()),
            "player_name": pa.array(columns[1], pa.string()),
            "player_short_name": pa.array([name.split()[0] for name in columns[1]], pa.string()),
            "team_id": pa.array(columns[2], pa.string()),
            "team_name": pa.array(columns[3], pa.string()),
            "position_group": pa.array(columns[4], pa.string()),
            "competition_edition_id": pa.array([EDITION] * len(rows), pa.string()),
            "count_match": pa.array(columns[5], pa.int64()),
            "total_distance_full_all": pa.array(columns[6], pa.float64()),
            "hsr_distance_full_tip": pa.array(columns[7], pa.float64()),
            "hsr_distance_full_otip": pa.array(columns[8], pa.float64()),
            "psv99": pa.array(columns[9], pa.float64()),
            "player_id": pa.array([1, 2, 2, 3, 4], pa.int64()),
        }
    )


@pytest.fixture
def physical_path(tmp_settings: Settings) -> Path:
    path = tmp_settings.dataset_root / RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(_physical_table(), path)
    return path


# -- registry ---------------------------------------------------------------------


def test_registry_resolves_skillcorner_column_grammar() -> None:
    physical = {
        spec.column: spec
        for spec in season.family_metrics(
            "physical",
            ["total_distance_full_all", "hsr_count_full_tip", "psv99", "minutes_full_otip"],
        )
    }
    assert physical["hsr_count_full_tip"].split == "tip"
    assert physical["hsr_count_full_tip"].base == "hsr_count"
    assert physical["hsr_count_full_tip"].basis == "per match (season mean)"
    assert physical["psv99"].unit == "km/h"
    assert physical["minutes_full_otip"].exposure is True

    obr = {
        spec.column: spec
        for spec in season.family_metrics(
            "obr",
            [
                "behindrun_count_p30tip",
                "overlaprun_count_dangerous_targeted_p30tip",
                "supportrun_avgdistance",
                "offballrun_count_total",
            ],
        )
    }
    assert obr["behindrun_count_p30tip"].basis == "per 30 min TIP"
    assert obr["overlaprun_count_dangerous_targeted_p30tip"].split == "dangerous_targeted"
    assert obr["supportrun_avgdistance"].unit == "m"
    assert obr["offballrun_count_total"].basis == "season total"

    passing = season.family_metrics("passing", ["pass_pct_completed", "pass_avgxpass_attempted"])
    assert {spec.unit for spec in passing} == {"%"}
    assert all(spec.metric_id.startswith("skillcorner.passing.") for spec in passing)


def test_registry_refuses_unknown_columns_and_families() -> None:
    with pytest.raises(season.SeasonDataError, match="not covered"):
        season.family_metrics("physical", ["total_distance_full_all", "mystery_metric"])
    with pytest.raises(season.SeasonDataError, match="no registered metric resolver"):
        season.family_metrics("ice_hockey", ["x"])
    # Identity/provenance columns are never offered as metrics.
    assert season.family_metrics("physical", ["player_id", "team_name", "subject_id"]) == []


# -- explicit denominators ----------------------------------------------------------


def test_rank_within_is_inclusive_and_excludes_missing_values() -> None:
    ranked = season.rank_within(3.0, [1.0, 2.0, 3.0, 3.0, None, 5.0])
    assert ranked.population_n == 6
    assert ranked.valid_n == 5
    assert ranked.rank == 2  # only 5.0 is larger
    assert ranked.percentile == 80.0  # 4 of 5 valid values are ≤ 3
    assert (ranked.minimum, ranked.median, ranked.maximum) == (1.0, 3.0, 5.0)

    missing = season.rank_within(None, [1.0, 2.0])
    assert missing.rank is None and missing.percentile is None and missing.valid_n == 2


def test_read_rows_projects_filters_and_bounds(physical_path: Path) -> None:
    total, rows = season.read_rows(
        physical_path,
        family="physical",
        metrics=["psv99"],
        filters=season.SeasonRowFilter(team_id="team-a"),
        limit=2,
    )
    assert total == 3
    assert len(rows) == 2
    assert set(rows[0]) == {*season.IDENTITY_COLUMNS, "count_match", "psv99"}

    total, _ = season.read_rows(
        physical_path,
        family="physical",
        metrics=[],
        filters=season.SeasonRowFilter(min_matches=10),
        limit=10,
    )
    assert total == 3

    with pytest.raises(season.SeasonDataError, match="not in this artifact"):
        season.read_rows(
            physical_path,
            family="physical",
            metrics=["sprint_count_full_all"],
            filters=season.SeasonRowFilter(),
            limit=1,
        )


def test_profile_names_its_population_and_picks_primary_row(physical_path: Path) -> None:
    payload = season.profile_payload(
        physical_path,
        family="physical",
        subject_id="sc/2",
        team_id=None,
        position_group=None,
        scope="position",
        min_matches=None,
        requested_metrics=["psv99", "total_distance_full_all"],
        edition_label="2024/2025",
        competition_name="Test League",
    )
    assert payload is not None
    # Ben Beta owns two rows; the one with most included matches is selected.
    assert payload["row"]["position_group"] == "Wide Attacker"
    population = payload["population"]
    assert population["scope"] == "position"
    assert population["rows"] == 1
    assert "Wide Attacker rows" in population["label"]

    centre = season.profile_payload(
        physical_path,
        family="physical",
        subject_id="sc/1",
        team_id=None,
        position_group=None,
        scope="position",
        min_matches=None,
        requested_metrics=["psv99"],
        edition_label="2024/2025",
        competition_name="Test League",
    )
    assert centre is not None
    psv = centre["metrics"][0]
    # Three Center Forward rows; one has no PSV-99, so the denominator is two.
    assert centre["population"]["rows"] == 3
    assert psv["valid_n"] == 2
    assert psv["rank"] == 2
    assert psv["percentile"] == 50.0

    thresholded = season.profile_payload(
        physical_path,
        family="physical",
        subject_id="sc/1",
        team_id=None,
        position_group=None,
        scope="edition",
        min_matches=10,
        requested_metrics=["total_distance_full_all"],
        edition_label="2024/2025",
        competition_name="Test League",
    )
    assert thresholded is not None
    assert thresholded["population"]["rows"] == 3
    assert thresholded["population"]["label"].endswith("≥10 included matches")

    assert (
        season.profile_payload(
            physical_path,
            family="physical",
            subject_id="sc/404",
            team_id=None,
            position_group=None,
            scope="edition",
            min_matches=None,
            requested_metrics=None,
            edition_label="x",
            competition_name="y",
        )
        is None
    )


# -- HTTP surface over the real backend assembly -----------------------------------------


class _SeasonBackend(PostgresServingBackend):
    def __init__(self, settings: Settings, path: Path) -> None:
        super().__init__(settings)
        self._path = path

    def season_editions(self) -> list[SeasonEditionView]:
        return [
            SeasonEditionView(
                dataset_id="season-test",
                provider="Test provider",
                sport_id="football",
                sport_name="Football",
                competition_id="competition-test",
                competition_name="Test League",
                edition_id=EDITION,
                edition_label="2024/2025",
                measurement_class="SOURCE_DERIVED",
                inclusion_rule=season.SKILLCORNER_INCLUSION_RULE,
                glossary_url=None,
                registry_version=season.SEASON_METRIC_REGISTRY_VERSION,
                license=LicenseView(
                    policy_id="lic",
                    identifier="MIT",
                    status="declared",
                    attribution_required=True,
                    noncommercial_only=False,
                    share_alike=False,
                    redistribution="conditional",
                    local_only=False,
                    restrictions=[],
                    notice="MIT; attribution required",
                ),
                families=[
                    SeasonFamilyRef(
                        family="physical",
                        label="Physical",
                        artifact_id="season-physical",
                        row_count=5,
                        checksum_sha256="0" * 64,
                        run_id="run-1",
                        grain_kind="PLAYER_SEASON",
                        grain_axes=["subject", "team", "competition_edition", "position_group"],
                        source_revision="rev",
                        source_file_key="physical.csv",
                        source_population_rows=5,
                        match_count_column="count_match",
                    )
                ],
            )
        ]

    def artifact(self, artifact_id: str) -> ArtifactRefView | None:
        if artifact_id != "season-physical":
            return None
        return ArtifactRefView(
            artifact_id=artifact_id,
            dataset_id="season-test",
            stream_id=None,
            layer="silver",
            relative_path=RELATIVE,
            format="parquet",
            compression=None,
            checksum_sha256="0" * 64,
            row_count=5,
            byte_size=None,
            artifact_kind="processing",
            modality=None,
            measurement_class="SOURCE_DERIVED",
            si_units=[],
            coordinate_frame_id=None,
            synchronization_spec_id=None,
        )


@pytest.fixture
def season_client(tmp_settings: Settings, physical_path: Path) -> TestClient:
    return TestClient(create_app(backend=_SeasonBackend(tmp_settings, physical_path)))


def test_season_family_route_serves_registry_and_facets(season_client: TestClient) -> None:
    body = season_client.get(f"/api/season/editions/{EDITION}/families/physical").json()
    assert body["population_rows"] == 5
    assert body["population_subjects"] == 4
    assert [team["display_name"] for team in body["teams"]] == ["Alpha FC", "Beta FC"]
    assert {metric["column"] for metric in body["metrics"]} >= {"psv99", "count_match"}

    missing = season_client.get(f"/api/season/editions/{EDITION}/families/passing")
    assert missing.status_code == 404
    assert season_client.get("/api/season/editions/nope/families/physical").status_code == 404


def test_season_rows_route_is_bounded_and_filtered(season_client: TestClient) -> None:
    response = season_client.get(
        f"/api/season/editions/{EDITION}/families/physical/rows",
        params={"metrics": "psv99", "position_group": "Center Forward", "limit": 2},
    )
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert len(page["rows"]) == 2
    assert page["metrics"] == ["psv99"]
    assert set(page["rows"][0]["values"]) == {"psv99"}

    subject = season_client.get(
        f"/api/season/editions/{EDITION}/families/physical/rows",
        params=[("subject_id", "sc/2"), ("metrics", "skillcorner.physical.psv99")],
    ).json()
    assert subject["total"] == 2

    unknown = season_client.get(
        f"/api/season/editions/{EDITION}/families/physical/rows", params={"metrics": "nope"}
    )
    assert unknown.status_code == 422


def test_season_profile_route_reports_denominator(season_client: TestClient) -> None:
    response = season_client.get(
        f"/api/season/editions/{EDITION}/families/physical/profile",
        params={"subject_id": "sc/1", "population": "team", "metrics": "total_distance_full_all"},
    )
    assert response.status_code == 200
    profile = response.json()
    assert profile["population"]["scope"] == "team"
    assert profile["population"]["rows"] == 3
    assert profile["population"]["label"].startswith("Alpha FC rows")
    assert profile["metrics"][0]["rank"] == 1
    assert profile["edition"]["measurement_class"] == "SOURCE_DERIVED"
    assert profile["family"]["run_id"] == "run-1"
    assert profile["caveats"]

    absent = season_client.get(
        f"/api/season/editions/{EDITION}/families/physical/profile",
        params={"subject_id": "sc/404"},
    )
    assert absent.status_code == 404
    invalid = season_client.get(
        f"/api/season/editions/{EDITION}/families/physical/profile",
        params={"subject_id": "sc/1", "population": "league"},
    )
    assert invalid.status_code == 422


def test_openapi_exposes_season_surface(tmp_settings: Settings, physical_path: Path) -> None:
    paths = create_app(backend=_SeasonBackend(tmp_settings, physical_path)).openapi()["paths"]
    for path in (
        "/api/season/editions",
        "/api/season/editions/{edition_id}/families/{family}",
        "/api/season/editions/{edition_id}/families/{family}/rows",
        "/api/season/editions/{edition_id}/families/{family}/profile",
        "/api/season/editions/{edition_id}/links",
    ):
        assert path in paths, path


def test_profile_can_rank_against_another_rows_denominator(physical_path: Path) -> None:
    # Di Delta (Midfield) ranked inside the Center Forward population: the
    # denominator is shared with a Center Forward comparison, and the payload says
    # the row is outside it rather than silently switching populations.
    payload = season.profile_payload(
        physical_path,
        family="physical",
        subject_id="sc/4",
        team_id=None,
        position_group=None,
        scope="position",
        min_matches=None,
        requested_metrics=["total_distance_full_all"],
        edition_label="2024/2025",
        competition_name="Test League",
        population_position_group="Center Forward",
    )
    assert payload is not None
    assert payload["population"]["rows"] == 3
    assert payload["population"]["position_group"] == "Center Forward"
    assert payload["population"]["selected_row_in_population"] is False
    assert payload["metrics"][0]["rank"] == 1  # 11 500 m exceeds every CF row
