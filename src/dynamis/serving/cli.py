"""``dynamis-serve``: run the analytical API locally.

The server is read-only with respect to science: it serves the PostgreSQL
control/Gold schemas and bounded Parquet windows. It never triggers a processor
or downloads data.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dynamis-serve", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="development auto-reload (requires the factory import path)",
    )
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)
    uvicorn.run(
        "dynamis.serving.app:app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
