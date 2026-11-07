"""Export the live FastAPI contract to specs/openapi.reference.json."""

from __future__ import annotations

import json
from pathlib import Path

from meridian.main import app

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "specs" / "openapi.reference.json"


def main() -> None:
    schema = app.openapi()
    TARGET.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {TARGET} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
