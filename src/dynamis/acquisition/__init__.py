"""Registry-driven acquisition: plan, download, verify, promote, manifest.

The acquisition boundary is deliberately small and explicit:

* :mod:`dynamis.acquisition.plan` turns a registry file selection into canonical,
  revision-pinned upstream URLs (no scraping, no implicit fetch-everything);
* :mod:`dynamis.acquisition.download` streams verified payloads to bounded
  ``.partial`` files and promotes them atomically;
* :mod:`dynamis.acquisition.runner` writes immutable Bronze evidence plus its
  manifest and receipt, and is idempotent on verified re-runs.

Nothing here mutates ``sources/registry.json``; local retrieval state belongs to
external Bronze manifests only.
"""

from dynamis.acquisition.download import (
    DownloadError,
    DownloadReceipt,
    FileDigest,
    IntegrityFailure,
    TransportFailure,
    UpstreamDriftError,
    digest_file,
    download_verified,
    git_blob_sha1_of,
)
from dynamis.acquisition.plan import (
    AcquisitionPlan,
    PlanError,
    PlannedFile,
    plan_acquisition,
    select_keys,
)
from dynamis.acquisition.resolvers import (
    HuggingFaceResolver,
    ProviderResolver,
    ResolvedFile,
    ResolverError,
    ZenodoResolver,
    resolver_for,
)
from dynamis.acquisition.runner import (
    AcquisitionReceipt,
    FileOutcome,
    ImmutableArtifactError,
    acquire,
)

__all__ = [
    "AcquisitionPlan",
    "AcquisitionReceipt",
    "DownloadError",
    "DownloadReceipt",
    "FileDigest",
    "FileOutcome",
    "HuggingFaceResolver",
    "ImmutableArtifactError",
    "IntegrityFailure",
    "PlanError",
    "PlannedFile",
    "ProviderResolver",
    "ResolvedFile",
    "ResolverError",
    "TransportFailure",
    "UpstreamDriftError",
    "ZenodoResolver",
    "acquire",
    "digest_file",
    "download_verified",
    "git_blob_sha1_of",
    "plan_acquisition",
    "resolver_for",
    "select_keys",
]
