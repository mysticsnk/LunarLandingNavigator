"""Register an inspected external Product 90 raster in the terrain catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.storage import get_repository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    dataset_id = get_repository().register_terrain_dataset(manifest)
    print(json.dumps({"dataset_id": dataset_id, "readiness": "ready"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
