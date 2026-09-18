"""Machine-readable dataset registry.

The registry is the acquisition authority: stable dataset identity, provider,
canonical URL/DOI, version, citation, modalities, expected files with expected
byte sizes and upstream checksums, retrieval state, locally computed checksums
once acquired, license identifier/status, attribution requirements, NC/SA
status, redistribution policy, local-only state, adapter id and optional/core
status.

Contracts live in :mod:`dynamis.contracts.domain`; this module only loads,
validates and audits registry documents. RES-96 never downloads data.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Collection, Sequence
from pathlib import Path

from pydantic import ValidationError

from dynamis.contracts.base import REGISTRY_SCHEMA_VERSION
from dynamis.contracts.domain import (
    DatasetRegistry,
    DatasetSource,
    DatasetVersion,
    LicensePolicy,
)
from dynamis.contracts.enums import Modality, RedistributionPolicy, RetrievalStatus
from dynamis.contracts.invariants import InvariantError

# Sources whose upstream record exposes no explicit license value. They stay
# local-only until rights are clarified; this list is the audit anchor for
# DATA_SOURCES.md and is asserted by tests so rights drift cannot pass silently.
# RES-104 captured the Zenodo API license id AND the rendered record Rights/
# License display for White and GymAware as cc-by-4.0, so those two sources
# moved to declared CC-BY-4.0; only TACKLE remains unclear/local-only.
LOCAL_ONLY_WHEN_RIGHTS_UNCLEAR = frozenset(
    {
        "tackle-workload",
    }
)

REQUIRED_LICENSE_IDENTIFIERS = {
    "womens-soccer-positioning": "CC-BY-NC-4.0",
    "white-cmj-acc-grf": "CC-BY-4.0",
    "gymaware-landmine-vision": "CC-BY-4.0",
    "dfl-sportec-idsse": "CC-BY-4.0",
    "skillcorner-opendata": "MIT",
    "spl-open-data": "CC-BY-NC-SA-4.0",
    "openbiomechanics": "CC-BY-NC-SA-4.0",
}

OPENBIOMECHANICS_EXCLUSION_MARKER = "professional sports organization"
#: SPL's own LICENSE at the pinned revision carries a role-dependent exclusion
#: in addition to CC BY-NC-SA 4.0; both must be preserved.
SPL_EXCLUSION_MARKERS = (
    "professional sports organization",
    "financial analysis",
    "significant shareholder",
)

# ---------------------------------------------------------------------------
# Acquisition eligibility acknowledgement
# ---------------------------------------------------------------------------

SPL_DATASET_ID = "spl-open-data"
SPL_LICENSE_ACKNOWLEDGEMENT = "spl-license-restrictions"

#: Source-specific acknowledgement tokens. The acknowledgement is deliberately
#: source-scoped so that satisfying one source's gate can never silently satisfy
#: an unrelated future license, and it is never inferred from stored profile or
#: context: absence refuses acquisition.
REQUIRED_ACKNOWLEDGEMENTS: dict[str, tuple[str, ...]] = {
    SPL_DATASET_ID: (SPL_LICENSE_ACKNOWLEDGEMENT,),
}


class RegistryError(ValueError):
    """Raised when the registry document is invalid or fails an audit rule."""


class AcknowledgementRequired(RegistryError):
    """An acquisition gate requires an explicit operator acknowledgement."""


def required_acknowledgements(dataset_id: str) -> tuple[str, ...]:
    return REQUIRED_ACKNOWLEDGEMENTS.get(dataset_id, ())


def assert_acquisition_acknowledged(source: DatasetSource, acknowledged: Collection[str]) -> None:
    """Fail closed unless every source-specific acknowledgement was given.

    The acknowledgement records that the operator has read the restriction; it
    does not assert legal eligibility and does not override any NC/SA term.
    """
    required = required_acknowledgements(source.dataset_id)
    missing = [token for token in required if token not in acknowledged]
    if not missing:
        return
    restrictions = " | ".join(source.license.restrictions) or "(restrictions not recorded)"
    flags = ", ".join(f"--acknowledge-{token}" for token in missing)
    raise AcknowledgementRequired(
        f"{source.dataset_id}: acquisition refused (fail-closed). The source's own "
        "license carries restrictions that the operator must acknowledge explicitly: "
        f"{restrictions} Acknowledge with {flags}. Eligibility to use the source "
        "remains the operator's responsibility; this acknowledgement does not "
        "override the non-commercial or share-alike obligations and does not assert "
        "that the operator is legally eligible."
    )


def default_registry_path() -> Path:
    from dynamis.config import repository_root

    return repository_root() / "sources" / "registry.json"


def load_registry(path: Path | str | None = None) -> DatasetRegistry:
    registry_path = Path(path) if path is not None else default_registry_path()
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"{registry_path} is not valid JSON: {exc}") from exc
    try:
        registry = DatasetRegistry.model_validate(payload)
    except ValidationError as exc:
        raise RegistryError(f"{registry_path} violates the registry contract:\n{exc}") from exc
    if registry.schema_version != REGISTRY_SCHEMA_VERSION:
        raise RegistryError(
            f"registry schema_version {registry.schema_version!r} is not supported "
            f"by this build (expected {REGISTRY_SCHEMA_VERSION!r})"
        )
    return registry


def source_by_id(registry: DatasetRegistry, dataset_id: str) -> DatasetSource:
    return registry.source(dataset_id)


def latest_version(source: DatasetSource) -> DatasetVersion:
    if not source.versions:
        raise RegistryError(f"dataset {source.dataset_id!r} declares no version")
    return source.versions[-1]


def _restriction_text(policy: LicensePolicy) -> str:
    return " ".join(policy.restrictions).lower()


def audit_registry(registry: DatasetRegistry) -> tuple[str, ...]:
    """Rights and integrity audit. Returns an ordered list of problems."""
    problems: list[str] = []
    for source in registry.sources:
        policy = source.license
        if policy.redistribution is RedistributionPolicy.PROHIBITED and not policy.local_only:
            problems.append(
                f"{source.dataset_id}: redistribution is prohibited but the source is not "
                "marked local-only"
            )
        if source.dataset_id in LOCAL_ONLY_WHEN_RIGHTS_UNCLEAR and not policy.local_only:
            problems.append(
                f"{source.dataset_id}: upstream record exposes no explicit license value, "
                "so the source must remain local-only until rights are clarified"
            )
        expected_identifier = REQUIRED_LICENSE_IDENTIFIERS.get(source.dataset_id)
        if expected_identifier is not None and policy.identifier != expected_identifier:
            problems.append(
                f"{source.dataset_id}: license identifier {policy.identifier!r} does not match "
                f"the audited value {expected_identifier!r}"
            )
        if source.dataset_id in LOCAL_ONLY_WHEN_RIGHTS_UNCLEAR and policy.identifier is not None:
            problems.append(
                f"{source.dataset_id}: an unclear-rights source must not assert a license "
                f"identifier (found {policy.identifier!r})"
            )
        if source.dataset_id == SPL_DATASET_ID:
            text = _restriction_text(policy)
            for marker in SPL_EXCLUSION_MARKERS:
                if marker not in text:
                    problems.append(
                        f"{SPL_DATASET_ID}: the role-dependent exclusion present in SPL's own "
                        f"LICENSE at the pinned revision must be preserved (missing {marker!r})"
                    )
            if "share-alike" not in text:
                problems.append(
                    f"{SPL_DATASET_ID}: CC BY-NC-SA 4.0 share-alike obligations must be recorded"
                )
        if source.dataset_id in REQUIRED_ACKNOWLEDGEMENTS and not policy.restrictions:
            problems.append(
                f"{source.dataset_id}: an acquisition acknowledgement gate exists but no "
                "source-specific restrictions are recorded for it"
            )
        if source.dataset_id == "openbiomechanics":
            if OPENBIOMECHANICS_EXCLUSION_MARKER not in _restriction_text(policy):
                problems.append(
                    "openbiomechanics: the additional professional-sports-organization / "
                    "financial-analysis exclusion must be preserved"
                )
            if not policy.noncommercial_only or not policy.share_alike:
                problems.append("openbiomechanics: NC and SA obligations must remain recorded")
        if not source.modalities:
            problems.append(f"{source.dataset_id}: no modality declared")
        for version in source.versions:
            if version.retrieval.status is RetrievalStatus.NOT_FETCHED:
                for item in version.retrieval.files:
                    if item.local_sha256 is not None:
                        problems.append(
                            f"{source.dataset_id}/{version.version}: file {item.key!r} claims a "
                            "local checksum while the version is not fetched"
                        )
            if version.retrieval.status is RetrievalStatus.FETCHED and not version.retrieval.files:
                problems.append(
                    f"{source.dataset_id}/{version.version}: fetched version lists no files"
                )
        if not source.adapter_id or not source.adapter_id.strip():
            problems.append(f"{source.dataset_id}: adapter id must be a non-empty value")
    for dataset_id, tokens in REQUIRED_ACKNOWLEDGEMENTS.items():
        if not tokens:
            problems.append(f"{dataset_id}: an acknowledgement gate must name a token")
    return tuple(problems)


def assert_registry_valid(registry: DatasetRegistry) -> None:
    """Raise :class:`RegistryError` if any audit rule fails."""
    problems = audit_registry(registry)
    if problems:
        raise RegistryError(
            "registry audit failed:\n" + "\n".join(f"  - {item}" for item in problems)
        )


def validate_registry(path: Path | str | None = None) -> DatasetRegistry:
    registry = load_registry(path)
    assert_registry_valid(registry)
    return registry


def describe_registry(registry: DatasetRegistry) -> str:
    """Human-readable summary used by the CLI and by the completion receipt."""
    lines = [f"registry schema_version={registry.schema_version} sources={len(registry.sources)}"]
    modality_counts: dict[str, int] = {}
    for source in registry.sources:
        for modality in source.modalities:
            modality_counts[modality.value] = modality_counts.get(modality.value, 0) + 1
    modalities = ", ".join(f"{name}={modality_counts[name]}" for name in sorted(modality_counts))
    lines.append(f"modalities: {modalities}")
    lines.append(
        "modality coverage: "
        + ("complete" if set(modality_counts) == {item.value for item in Modality} else "partial")
    )
    for source in registry.sources:
        policy = source.license
        flags = [
            "optional" if latest_version(source).optional else "core",
            "local-only" if policy.local_only else "redistributable-conditional",
            f"license={policy.identifier or 'unclear'}",
            f"retrieval={latest_version(source).retrieval.status.value}",
        ]
        lines.append(f"  {source.dataset_id}: {', '.join(flags)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: ``dynamis-registry-validate``."""
    parser = argparse.ArgumentParser(
        prog="dynamis-registry-validate",
        description=(
            "Validate the DynamisData dataset registry against the contract and the "
            "audited license/rights rules. Never downloads data."
        ),
    )
    parser.add_argument("--registry", type=Path, default=None, help="Path to registry.json")
    parser.add_argument("--quiet", action="store_true", help="Suppress the summary")
    args = parser.parse_args(argv)

    try:
        registry = validate_registry(args.registry)
    except (RegistryError, InvariantError) as exc:
        print(f"registry validation FAILED: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(describe_registry(registry))
    print("registry validation PASSED")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via console script
    raise SystemExit(main())
