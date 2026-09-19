"""Export the FastAPI OpenAPI document for the generated TypeScript client.

The FastAPI application is the API schema authority; the browser types are
generated from this document (``openapi-typescript``) and checked for drift in
CI. Writing is deterministic: sorted keys, fixed indent, trailing newline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dynamis.config import repository_root
from dynamis.serving.app import create_app

DEFAULT_TARGET = Path("apps") / "web" / "src" / "api" / "openapi.json"


def export(target: Path | None = None) -> Path:
    """Write the deterministic OpenAPI document and return its path."""
    app = create_app()
    document = app.openapi()
    destination = target or (repository_root() / DEFAULT_TARGET)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    destination.write_text(text, encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dynamis-openapi", description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    destination = export(args.out)
    print(destination.as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
