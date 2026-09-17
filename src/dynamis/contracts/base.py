"""Shared contract primitives.

This module is the single source of truth for the constrained scalar types and
the frozen Pydantic base class used by every DynamisData contract. Contract
modules must import these definitions instead of redefining them locally.
"""

from __future__ import annotations

from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_SCHEMA_VERSION: Final = "1"
REGISTRY_SCHEMA_VERSION: Final = "1"

Identifier = Annotated[str, Field(min_length=1, max_length=256)]

DatasetId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=64)]

SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MD5 = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
SHA1 = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
GitSHA = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]

PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
UnitInterval = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]

Vec3 = Annotated[tuple[float, float, float], Field(min_length=3, max_length=3)]
Quaternion = Annotated[tuple[float, float, float, float], Field(min_length=4, max_length=4)]


class Contract(BaseModel):
    """Frozen, forward-incompatible base for all DynamisData contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
