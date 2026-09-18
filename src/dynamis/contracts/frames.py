"""Coordinate-frame and skeleton authorities.

Nothing in DynamisData may swap axes, flip signs, rotate a pitch, or transform
between camera and world space implicitly. Every frame and every frame-to-frame
transform is declared here, together with the algorithm or written
justification that produced it, so a reviewer can reconstruct the exact
geometric meaning of every coordinate column.

The single supported application path is :func:`transform_points`, which
requires an explicit :class:`FrameTransform` instance.
"""

from __future__ import annotations

import math

from pydantic import AwareDatetime, Field, model_validator

from dynamis.contracts.base import (
    Contract,
    Identifier,
    NonNegativeFloat,
    Quaternion,
    Vec3,
)
from dynamis.contracts.enums import AxisDirection, FrameKind, Handedness
from dynamis.contracts.units import assert_si_unit

_QUATERNION_NORM_TOLERANCE = 1e-6
_UNDIRECTED = frozenset({AxisDirection.UNSPECIFIED, AxisDirection.ORIGIN_DEPENDENT})


class FrameTransform(Contract):
    """Explicit rigid transform from ``source_frame_id`` into ``target_frame_id``.

    ``algorithm_id`` names the code that produced the transform. When no
    algorithm exists yet, free-text ``notes`` is mandatory: an unexplained
    transform is never acceptable.
    """

    source_frame_id: Identifier
    target_frame_id: Identifier
    translation_m: Vec3
    rotation_xyzw: Quaternion
    applied_at: AwareDatetime | None = None
    algorithm_id: Identifier | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def check_transform(self) -> FrameTransform:
        if self.source_frame_id == self.target_frame_id:
            raise ValueError("a frame transform must not be self-referential")
        norm = math.sqrt(sum(component * component for component in self.rotation_xyzw))
        if abs(norm - 1.0) > _QUATERNION_NORM_TOLERANCE:
            raise ValueError(f"rotation_xyzw must be a unit quaternion (|q|={norm!r})")
        if self.algorithm_id is None and not (self.notes and self.notes.strip()):
            raise ValueError(
                "a frame transform requires an algorithm_id or an explicit written justification"
            )
        return self


class CoordinateFrame(Contract):
    """Declared geometric reference for coordinate-valued columns."""

    frame_id: Identifier
    name: str = Field(min_length=1)
    kind: FrameKind
    handedness: Handedness
    x_direction: AxisDirection
    y_direction: AxisDirection
    z_direction: AxisDirection
    origin_description: str = Field(min_length=1)
    length_unit: str = "m"
    parent_frame_id: Identifier | None = None
    transform: FrameTransform | None = None
    description: str | None = None

    @model_validator(mode="after")
    def check_frame(self) -> CoordinateFrame:
        assert_si_unit(self.length_unit, field_name="CoordinateFrame.length_unit")
        directions = (self.x_direction, self.y_direction, self.z_direction)
        for first, second in ((0, 1), (0, 2), (1, 2)):
            if directions[first] == directions[second] and directions[first] not in _UNDIRECTED:
                raise ValueError(
                    f"axis directions must be distinct: {directions[first]!r} is declared twice"
                )
        if self.parent_frame_id is None and self.transform is not None:
            raise ValueError("a transform requires an explicit parent_frame_id")
        if self.parent_frame_id is not None and self.transform is None:
            raise ValueError(
                "a declared parent frame requires an explicit transform; "
                "hidden or implicit transforms are forbidden"
            )
        if self.transform is not None and self.transform.target_frame_id != self.parent_frame_id:
            raise ValueError(
                "transform.target_frame_id must equal the declared parent_frame_id "
                f"({self.transform.target_frame_id!r} != {self.parent_frame_id!r})"
            )
        if self.kind is FrameKind.UNKNOWN and not (self.description and self.description.strip()):
            raise ValueError("an unknown frame kind requires an explicit description")
        if self.handedness is Handedness.UNSPECIFIED and not (
            self.description and self.description.strip()
        ):
            raise ValueError(
                "an unspecified handedness is a deliberate declaration and requires "
                "an explicit description"
            )
        return self


class JointDefinition(Contract):
    joint_id: int = Field(ge=0)
    joint_name: str = Field(min_length=1)
    parent_joint_id: int | None = None


class SkeletonDefinition(Contract):
    """Joint topology authority.

    Joint indices are meaningless without the skeleton they belong to, so pose
    rows carry ``skeleton_id`` and resolution is always explicit.
    """

    skeleton_id: Identifier
    name: str = Field(min_length=1)
    joint_count: int = Field(gt=0)
    joints: tuple[JointDefinition, ...] = Field(min_length=1)
    description: str | None = None

    @model_validator(mode="after")
    def check_skeleton(self) -> SkeletonDefinition:
        if len(self.joints) != self.joint_count:
            raise ValueError(
                f"joint_count={self.joint_count} does not match {len(self.joints)} joints"
            )
        names: set[str] = set()
        roots = 0
        for position, joint in enumerate(self.joints):
            if joint.joint_id != position:
                raise ValueError(
                    f"joints must be ordered and index-aligned; expected joint_id={position}, "
                    f"found {joint.joint_id}"
                )
            if joint.joint_name in names:
                raise ValueError(f"duplicate joint_name {joint.joint_name!r}")
            names.add(joint.joint_name)
            if joint.parent_joint_id is None:
                roots += 1
            elif joint.parent_joint_id >= joint.joint_id:
                raise ValueError(
                    f"joint {joint.joint_name!r} must reference an earlier parent joint"
                )
        if roots != 1:
            raise ValueError(f"skeleton must declare exactly one root joint, found {roots}")
        return self


def quaternion_to_rotation_matrix(quaternion_xyzw: Quaternion) -> tuple[Vec3, Vec3, Vec3]:
    """Row-major 3x3 rotation matrix from a unit quaternion (explicit math)."""
    x, y, z, w = quaternion_xyzw
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)),
        (2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)),
        (2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)),
    )


def transform_points(
    transform: FrameTransform,
    points_m: tuple[Vec3, ...],
) -> tuple[Vec3, ...]:
    """Apply one declared rigid transform to explicit points.

    This is the only supported coordinate transformation path; callers must pass
    the transform they intend to apply, so no geometric change can occur
    implicitly.
    """
    rotation = quaternion_to_rotation_matrix(transform.rotation_xyzw)
    tx, ty, tz = transform.translation_m
    transformed: list[Vec3] = []
    for px, py, pz in points_m:
        transformed.append(
            (
                rotation[0][0] * px + rotation[0][1] * py + rotation[0][2] * pz + tx,
                rotation[1][0] * px + rotation[1][1] * py + rotation[1][2] * pz + ty,
                rotation[2][0] * px + rotation[2][1] * py + rotation[2][2] * pz + tz,
            )
        )
    return tuple(transformed)


def transform_residual_m(transform: FrameTransform, point_m: Vec3) -> NonNegativeFloat:
    """Distance between a point and its transformed image (self-consistency probe)."""
    (image,) = transform_points(transform, (point_m,))
    return float(math.sqrt(sum((image[index] - point_m[index]) ** 2 for index in range(3))))
