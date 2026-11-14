"""Acquire and integrity-check the official LOLA terrain source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT_SECONDS = 30.0
LARGE_FILE_THRESHOLD_BYTES = 1_000_000_000


@dataclass(frozen=True)
class TerrainProduct:
    product_id: str
    area: str
    version: str | None
    source_url: str
    metadata_url: str
    expected_bytes: int
    width: int
    height: int
    resolution_m: float
    tiff_magic: bytes
    footprint: str
    source_reference_radius_m: int | None


PRODUCTS = {
    product.product_id: product
    for product in (
        TerrainProduct(
            "Site01_final_adj_5mpp_surf.tif",
            "Shackleton Connecting Ridge",
            None,
            "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site01/Site01_final_adj_5mpp_surf.tif",
            "https://pgda.gsfc.nasa.gov/products/78",
            40_980_810,
            3200,
            3200,
            5.0,
            b"II*\x00",
            "Product 78 Site01 local raster; 5 m cells; X [-19000, -3000] m, Y [-20000, -4000] m",
            None,
        ),
        TerrainProduct(
            "LM7_final_adj_5mpp_surf.tif",
            "Faustini Rim A",
            None,
            "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/LM7/LM7_final_adj_5mpp_surf.tif",
            "https://pgda.gsfc.nasa.gov/products/78",
            64_033_675,
            4000,
            4000,
            5.0,
            b"II*\x00",
            "Product 78 LM7 local raster; 5 m cells; X [54000, 74000] m, Y [-10000, 10000] m",
            None,
        ),
        TerrainProduct(
            "Site07_final_adj_5mpp_surf.tif",
            "Peak near Shackleton",
            None,
            "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site07/Site07_final_adj_5mpp_surf.tif",
            "https://pgda.gsfc.nasa.gov/products/78",
            40_980_808,
            3200,
            3200,
            5.0,
            b"II*\x00",
            "Product 78 Site07 local raster; 5 m cells; X [22000, 38000] m, Y [-28000, -12000] m",
            None,
        ),
        TerrainProduct(
            "LDEM_80S_20MPP_ADJ.TIF",
            "South polar regional coverage, including the south pole",
            None,
            "https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_80S_20MPP_ADJ.TIF",
            "https://pgda.gsfc.nasa.gov/products/90",
            2_696_082_051,
            30400,
            30400,
            20.0,
            b"II+\x00",
            "Product 90 coverage 80 degrees south through the south pole to 90 degrees south",
            None,
        ),
    )
}


def default_data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "LunarLandingNavigator" / "terrain"


def external_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return resolved
    raise ValueError("terrain source and manifest files must be stored outside the repository")


def verify_file(
    product: TerrainProduct, path: Path, expected_sha256: str | None = None
) -> dict[str, object]:
    path = external_path(path)
    if expected_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("expected_sha256 must contain 64 hexadecimal characters")
    if path.stat().st_size != product.expected_bytes:
        raise ValueError(
            f"file size mismatch: expected {product.expected_bytes}, got {path.stat().st_size}"
        )
    with path.open("rb") as source:
        if source.read(len(product.tiff_magic)) != product.tiff_magic:
            raise ValueError("file does not have the expected TIFF byte-order and version header")
        source.seek(0)
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise ValueError("SHA-256 checksum mismatch")
    return product_manifest(product, path, digest, expected_sha256 is not None)


def product_manifest(
    product: TerrainProduct,
    path: Path,
    sha256: str,
    checksum_pinned: bool,
) -> dict[str, object]:
    product_metadata = asdict(product)
    product_metadata["tiff_magic"] = product.tiff_magic.hex()
    return {
        **product_metadata,
        "path": str(path),
        "size_bytes": product.expected_bytes,
        "sha256": sha256,
        "checksum_pinned": checksum_pinned,
        "source_frame": "MOON_ME / JPL DE421",
        "source_projection": "South polar stereographic, metres, centered at the south pole",
        "source_elevation": "Float32 surface height in metres; source no-data is NaN",
        "target_reference_radius_m": 1_737_400,
        "preparation_status": "source_size_and_tiff_signature_checked_not_horizon_ready",
        "processing_parameters": {
            "horizontal_transform": "Preserve official south polar stereographic X/Y metres",
            "vertical_transform": "Not applied; confirm product-specific vertical reference first",
            "no_data": "Map NaN to unavailable; never replace or interpolate it",
            "output_grid": None,
        },
    }


def download_file(
    product: TerrainProduct,
    destination: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    destination = external_path(destination)
    if not 0.0 < timeout_seconds <= 300.0:
        raise ValueError("timeout_seconds must be in (0, 300]")
    if expected_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("expected_sha256 must contain 64 hexadecimal characters")
    if product.expected_bytes >= LARGE_FILE_THRESHOLD_BYTES:
        raise ValueError(
            "large source file download is disabled; inspect metadata or download manually"
        )
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing source file: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=destination.name + ".",
            suffix=".part",
            dir=destination.parent,
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            request = Request(
                product.source_url, headers={"User-Agent": "LunarLandingNavigator/1.0"}
            )
            with urlopen(request, timeout=timeout_seconds) as response:
                announced = response.headers.get("Content-Length")
                if announced is not None and int(announced) != product.expected_bytes:
                    raise ValueError("provider Content-Length does not match verified product size")
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > product.expected_bytes:
                        raise ValueError("provider response exceeds verified product size")
                    output.write(chunk)
        manifest = verify_file(product, temporary_path, expected_sha256)
        os.replace(temporary_path, destination)
        temporary_path = None
        manifest["path"] = str(destination)
        return manifest
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_manifest(manifest: dict[str, object], directory: Path, product_id: str) -> Path:
    directory = external_path(directory)
    target = directory / f"{product_id}.terrain.json"
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product_id", choices=sorted(PRODUCTS))
    parser.add_argument("--file", type=Path, help="Verify an already downloaded source file")
    parser.add_argument(
        "--download", action="store_true", help="Download the small official source file"
    )
    parser.add_argument("--data-dir", type=Path, default=default_data_directory())
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--sha256", help="Expected checksum from a trusted prior verification")
    args = parser.parse_args()
    if bool(args.file) == args.download:
        parser.error("choose exactly one of --file or --download")
    product = PRODUCTS[args.product_id]
    path = (
        external_path(args.file) if args.file else external_path(args.data_dir) / product.product_id
    )
    manifest = (
        download_file(
            product,
            path,
            timeout_seconds=args.timeout,
            expected_sha256=args.sha256,
        )
        if args.download
        else verify_file(product, path, args.sha256)
    )
    manifest_path = write_manifest(manifest, path.parent, product.product_id)
    print(
        json.dumps(
            {
                "inspected_file": str(path),
                "manifest": str(manifest_path),
                "sha256": manifest["sha256"],
                "preparation_status": manifest["preparation_status"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
