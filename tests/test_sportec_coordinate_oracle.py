"""Independent Sportec coordinate-system oracle against pinned executable Kloppy.

DynamisETL maps provider event coordinates (bottom-left origin) into the
pitch-centre tracking frame through one explicit pure translation. Kloppy is the
reference reader named by the dataset card, and its prose is internally
inconsistent (the ``SportecEventDataCoordinateSystem`` docstring says the y-axis
is oriented top-to-bottom) while its *executable* properties return
``BOTTOM_TO_TOP`` for both event and tracking systems.

This test does not read prose. It executes the pinned Kloppy transformation
(``DatasetTransformer`` from ``SportecEventDataCoordinateSystem`` to
``SportecTrackingDataCoordinateSystem`` at the declared metric pitch
dimensions) on structurally synthetic points and requires DynamisETL's
``transform_points`` to agree within floating-point tolerance.

The real J03WPY comparison (all coordinate-bearing events) is executed locally
by ``scripts/kloppy_sportec_oracle.py`` against immutable Bronze; its verdict
and deltas are recorded in an external receipt. No real coordinates are
committed.

Kloppy is pinned exactly in ``pyproject.toml`` (``kloppy==3.19.0``).
"""

from __future__ import annotations

import kloppy
from kloppy.domain import (
    DatasetTransformer,
    Origin,
    Point,
    SportecEventDataCoordinateSystem,
    SportecTrackingDataCoordinateSystem,
    VerticalOrientation,
)

from dynamis.adapters.sportec_idsse.authorities import corner_to_center_transform
from dynamis.contracts import transform_points

#: Kloppy revision the oracle is pinned to; bump deliberately and re-run the
#: real-data oracle whenever this changes.
PINNED_KLOPPY_VERSION = "3.19.0"

PITCH_X_M = 105.0
PITCH_Y_M = 68.0
TOLERANCE_M = 1e-9

#: Structurally synthetic points spanning both halves, both touchlines and the
#: pitch centre; deliberately no real provider row.
SYNTHETIC_POINTS: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (105.0, 68.0),
    (0.0, 68.0),
    (105.0, 0.0),
    (52.5, 34.0),
    (70.0, 20.0),
    (10.0, 60.0),
    (40.0, 34.0),
    (99.9, 0.1),
    (0.1, 67.9),
)


def test_pinned_kloppy_version_is_installed() -> None:
    assert kloppy.__version__ == PINNED_KLOPPY_VERSION


def test_kloppy_executable_sportec_orientations_are_bottom_to_top() -> None:
    event_system = SportecEventDataCoordinateSystem(pitch_length=PITCH_X_M, pitch_width=PITCH_Y_M)
    tracking_system = SportecTrackingDataCoordinateSystem(
        pitch_length=PITCH_X_M, pitch_width=PITCH_Y_M
    )
    assert event_system.origin is Origin.BOTTOM_LEFT
    assert event_system.vertical_orientation is VerticalOrientation.BOTTOM_TO_TOP
    assert tracking_system.origin is Origin.CENTER
    assert tracking_system.vertical_orientation is VerticalOrientation.BOTTOM_TO_TOP


def test_dynamisetl_event_transform_matches_executable_kloppy() -> None:
    transformer = DatasetTransformer(
        from_coordinate_system=SportecEventDataCoordinateSystem(
            pitch_length=PITCH_X_M, pitch_width=PITCH_Y_M
        ),
        to_coordinate_system=SportecTrackingDataCoordinateSystem(
            pitch_length=PITCH_X_M, pitch_width=PITCH_Y_M
        ),
    )
    transform = corner_to_center_transform(PITCH_X_M, PITCH_Y_M)
    for x_source, y_source in SYNTHETIC_POINTS:
        reference = transformer.change_point_dimensions(Point(x=x_source, y=y_source))
        assert reference is not None
        ((x_m, y_m, _z),) = transform_points(transform, ((x_source, y_source, 0.0),))
        assert abs(x_m - reference.x) <= TOLERANCE_M
        assert abs(y_m - reference.y) <= TOLERANCE_M
