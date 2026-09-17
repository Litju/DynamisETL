"""Canonical enumerations.

Single authority for every closed vocabulary in DynamisData. Adapters and
processors must import these values; they must never restate them locally.
"""

from __future__ import annotations

from enum import StrEnum


class MeasurementClass(StrEnum):
    """Scientific classification of every measured or produced value.

    The four members are exact and must not be extended, renamed or merged.
    """

    RAW_MEASURED = "RAW_MEASURED"
    SOURCE_DERIVED = "SOURCE_DERIVED"
    PIPELINE_DERIVED = "PIPELINE_DERIVED"
    MODEL_ESTIMATED = "MODEL_ESTIMATED"


class Modality(StrEnum):
    """V1 scientific modalities. Each value has one canonical Arrow schema."""

    GNSS = "gnss"
    IMU = "imu"
    FORCE = "force"
    LPT = "lpt"
    TRACKING = "tracking"
    EVENT = "event"
    POSE = "pose"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class QualityState(StrEnum):
    VALID = "VALID"
    QUARANTINED = "QUARANTINED"


class SessionKind(StrEnum):
    """A session may be individual (laboratory) or collective (team/match).

    Collective sessions carry their participants through ``SessionParticipant``
    so a single match identity is never duplicated per player.
    """

    INDIVIDUAL = "individual"
    TEAM = "team"
    MATCH = "match"
    LABORATORY = "laboratory"
    LONGITUDINAL = "longitudinal"
    UNKNOWN = "unknown"


class ParticipantRole(StrEnum):
    ATHLETE = "athlete"
    PLAYER = "player"
    GOALKEEPER = "goalkeeper"
    PATIENT = "patient"
    PARTICIPANT = "participant"
    OPERATOR = "operator"
    UNKNOWN = "unknown"


class Timebase(StrEnum):
    UTC = "utc"
    GNSS_UTC = "gnss_utc"
    DEVICE_MONOTONIC = "device_monotonic"
    SESSION_MONOTONIC = "session_monotonic"
    GPS_WEEK_TIME = "gps_week_time"
    UNKNOWN = "unknown"


class SynchronizationMethod(StrEnum):
    SOURCE_PROVIDED = "source_provided"
    HARDWARE_SYNCHRONIZED = "hardware_synchronized"
    EVENT_ALIGNED = "event_aligned"
    CROSS_CORRELATION_ALIGNED = "cross_correlation_aligned"
    SOFTWARE_TIMESTAMPED = "software_timestamped"
    UNKNOWN = "unknown"


class FrameKind(StrEnum):
    WORLD_GEODETIC = "world_geodetic"
    LOCAL_ENU = "local_enu"
    PITCH = "pitch"
    BODY = "body"
    SENSOR = "sensor"
    CAMERA = "camera"
    LABORATORY = "laboratory"
    JOINT_LOCAL = "joint_local"
    UNKNOWN = "unknown"


class Handedness(StrEnum):
    RIGHT = "right"
    LEFT = "left"


class AxisDirection(StrEnum):
    """Physical direction an axis points at, relative to a named reference."""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    UP = "up"
    DOWN = "down"
    TOWARDS_OPPONENT_GOAL = "towards_opponent_goal"
    TOWARDS_OWN_GOAL = "towards_own_goal"
    TOWARDS_ATTACKING_BASKET = "towards_attacking_basket"
    TOWARDS_DEFENDING_BASKET = "towards_defending_basket"
    RIGHT = "right"
    LEFT = "left"
    FORWARD = "forward"
    BACKWARD = "backward"
    LONG_AXIS = "long_axis"
    SHORT_AXIS = "short_axis"
    ALONG_CABLE = "along_cable"
    ORIGIN_DEPENDENT = "origin_dependent"
    UNSPECIFIED = "unspecified"


class LicenseStatus(StrEnum):
    DECLARED = "declared"
    UNCLEAR = "unclear"


class RedistributionPolicy(StrEnum):
    CONDITIONAL = "conditional"
    PROHIBITED = "prohibited"


class RetrievalStatus(StrEnum):
    NOT_FETCHED = "not_fetched"
    FETCHED = "fetched"
    FAILED = "failed"


class ArtifactLayer(StrEnum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    QUARANTINE = "quarantine"
    CACHE = "cache"
    TMP = "tmp"


class ArtifactFormat(StrEnum):
    PARQUET = "parquet"
    ARROW_IPC = "arrow_ipc"
    JSON = "json"
    CSV = "csv"
    TEXT = "text"
    NATIVE = "native"


class Compression(StrEnum):
    NONE = "none"
    ZSTD = "zstd"
    SNAPPY = "snappy"


class ProcessingStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AlgorithmKind(StrEnum):
    ADAPTER = "adapter"
    CANONICALIZER = "canonicalizer"
    QC_RULE = "qc_rule"
    PROCESSOR = "processor"
    METRIC = "metric"
    EXPORTER = "exporter"


class MetricValueKind(StrEnum):
    SCALAR = "scalar"
    SERIES = "series"
    CATEGORICAL = "categorical"
    VECTOR = "vector"


STREAM_ID_LENGTH = 8


def make_stream_id(modality: Modality, ordinal: int) -> str:
    """Deterministic synthetic stream identity: ``<modality>-<zero-padded>``."""
    if ordinal < 0:
        raise ValueError("stream ordinal must be non-negative")
    return f"{modality.value}-{ordinal:0{STREAM_ID_LENGTH}d}"
