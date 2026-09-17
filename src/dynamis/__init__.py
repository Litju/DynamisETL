"""DynamisData: multimodal human-performance data platform.

RES-96 provides the bootstrap foundation only: canonical contracts, typed Arrow
modality schemas, a dataset registry, deterministic storage conventions,
synthetic fixtures, the PostgreSQL metadata schema and the orchestration
skeleton. Provider adapters, production metrics, ML and the visualization
product are later issues.

This module intentionally imports nothing, so tooling that must run before the
environment is installed (for example :mod:`dynamis.guard`) can import the
package without pulling third-party dependencies. Import the contract surface
from :mod:`dynamis.contracts`.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
